import os
import re
import httpx
from fastapi import HTTPException, status, APIRouter
from google import genai
from google.genai import types
import schemas

router = APIRouter()
client = genai.Client()

BACKEND_SERVICE_URL = os.getenv("BACKEND_SERVICE_URL", "http://localhost:8000/api")

# ----------------------------------------------------------------
# CONTEXT & HISTORY UTILITIES
# ----------------------------------------------------------------
async def fetch_business_data_from_backend(business_id: str) -> dict:
    url = f"{BACKEND_SERVICE_URL}/businesses/{business_id}"
    headers = {"Authorization": f"Bearer {os.getenv('INTERNAL_AUTH_KEY')}"}
    async with httpx.AsyncClient() as httpx_client:
        try:
            response = await httpx_client.get(url, headers=headers, timeout=5.0)
            if response.status_code == 200:
                return response.json() 
        except httpx.RequestError:
            pass
            
    return {
        "name": "Mama Tope Kitchen",
        "catalog": "Jollof Rice: N3000, Fried Rice: N3500, Grilled Chicken: N1500"
    }

def format_history_for_openai(history: list[schemas.Message], user_msg: str) -> list:
    """Formats Pydantic history into standard OpenAI/Groq/OpenRouter message lists."""
    formatted = []
    for msg in history:
        # Map assistant/user roles cleanly
        role = "assistant" if msg.role == "assistant" else "user"
        formatted.append({"role": role, "content": msg.content})
    
    # Append the incoming current message at the end of the timeline
    formatted.append({"role": "user", "content": user_msg})
    return formatted

def format_history_for_gemini(history: list[schemas.Message], user_msg: str) -> list:
    """Formats Pydantic history into Google GenAI SDK Content types."""
    formatted = []
    for msg in history:
        role = "model" if msg.role == "assistant" else "user"
        formatted.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=msg.content)]
            )
        )
    # Append current message
    formatted.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_msg)]
        )
    )
    return formatted


# ----------------------------------------------------------------
# MULTI-TIER AI EXECUTORS WITH HISTORY
# ----------------------------------------------------------------
async def call_tier2_groq(openai_messages: list, system_instruction: str) -> str:
    url = "https://api.groq.com/openapi/v1/chat/completions"
    api_key = os.getenv("GROQ_API_KEY") 
    if not api_key:
        raise ValueError("Groq API Key missing")

    payload = {
        "model": "llama-3.1-8b-instant",
        # Groq takes system prompt directly in the messages array
        "messages": [{"role": "system", "content": system_instruction}] + openai_messages,
        "temperature": 0.2
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient() as httpx_client:
        response = await httpx_client.post(url, json=payload, headers=headers, timeout=6.0)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        raise RuntimeError("Tier 2 Groq failed")


async def call_tier3_openrouter(openai_messages: list, system_instruction: str) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    api_key = os.getenv("OPENROUTER_API_KEY") 
    if not api_key:
        raise ValueError("Tier 3 OpenRouter key missing")

    payload = {
        "model": "meta-llama/llama-3.1-8b-instruct:free",
        "messages": [{"role": "system", "content": system_instruction}] + openai_messages,
        "temperature": 0.2
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "PayMate AI Webhook"
    }

    async with httpx.AsyncClient() as httpx_client:
        response = await httpx_client.post(url, json=payload, headers=headers, timeout=8.0)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        raise RuntimeError(f"Tier 3 OpenRouter failed")


# ----------------------------------------------------------------
# ENDPOINT GATEWAY
# ----------------------------------------------------------------
@router.post("/bot", response_model=schemas.ChatResponse)
async def whatsapp_webhook(payload: schemas.ChatRequest, business_id: str):
    """
    Accepts the new structured ChatRequest schema containing history.
    business_id can be passed as a query param or added to ChatRequest.
    """
    # 1. Regex Interception
    clean_message = payload.message.strip().lower()
    if re.search(r'\b(human|agent|support|talk to owner|help)\b', clean_message):
        return schemas.ChatResponse(
            reply="I'm flagging your query for the business owner right now. Hang tight!",
            action={"type": "HUMAN_HANDOFF"}
        )
    
    # 2. Dynamic Context Pull
    biz_data = await fetch_business_data_from_backend(business_id)
    
    system_instruction = (
        f"You are PayMate AI, the store assistant for '{biz_data['name']}'.\n"
        f"Live Catalog:\n{biz_data['catalog']}\n\n"
        f"Review the conversation history to understand context. "
        f"If the user explicitly confirms they want to buy/checkout, calculate the exact total cost "
        f"and append this trigger code on a brand new line at the very end: [TRIGGER_PAYMENT: amount]"
    )

    # Prepare message blocks based on API formats
    openai_messages = format_history_for_openai(payload.history, payload.message)
    gemini_messages = format_history_for_gemini(payload.history, payload.message)

    ai_reply = None

    # TIER 1: Gemini
    if os.getenv("GEMINI_API_KEY"):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=gemini_messages,  # Passing full conversation history array
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                )
            )
            ai_reply = response.text
        except Exception as e:
            if "503" not in str(e) and "UNAVAILABLE" not in str(e).upper():
                raise HTTPException(status_code=500, detail=str(e))

    # TIER 2: Groq
    if not ai_reply:
        try:
            ai_reply = await call_tier2_groq(openai_messages, system_instruction)
        except Exception:
            pass

    # TIER 3: OpenRouter
    if not ai_reply:
        try:
            ai_reply = await call_tier3_openrouter(openai_messages, system_instruction)
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"All layers offline: {str(e)}")

    # 3. Post-processing Structural Action Tags
    payment_match = re.search(r'\[TRIGGER_PAYMENT:\s*(\d+)\]', ai_reply)
    if payment_match:
        extracted_amount = payment_match.group(1)
        clean_reply = re.sub(r'\[TRIGGER_PAYMENT:\s*\d+\]', '', ai_reply).strip()
        
        return schemas.ChatResponse(
            reply=clean_reply,
            action={
                "type": "COLLECT_PAYMENT",
                "amount": int(extracted_amount),
                "business_name": biz_data['name']
            }
        )

    return schemas.ChatResponse(reply=ai_reply)