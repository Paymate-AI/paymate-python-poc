import os
import re
import httpx
import asyncio
from fastapi import HTTPException, status, APIRouter
from google import genai
from google.genai import types
import schemas

router = APIRouter()
client = genai.Client()

BACKEND_SERVICE_URL = os.getenv("BACKEND_SERVICE_URL", "http://localhost:8000/api")

FAILURE_TRACKER = {}

def sanitize_input(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'<[^>]*>', '', text)
    text = text.replace("```", "").replace("`", "")
    text = re.sub(r'[\*\_~#\-]', '', text)
    text = re.sub(r'[\[\]\{\}]', '', text)
    return " ".join(text.split())

def check_guardrails(text: str) -> tuple[bool, str | None]:
    clean_text = text.lower()
    insult_pattern = r'\b(stupid|idiot|fool|useless|bastard|mad|craze|mumu|maggot|fuck|shattered|trash|foolish)\b'
    if re.search(insult_pattern, clean_text):
        return True, "Let's keep things professional. Please let me know how I can help with your order."
        
    manipulation_pattern = r'\b(system prompt|ignore previous|act as|you are now|developer mode|override|ignore previous instructions|send money)\b'
    if re.search(manipulation_pattern, clean_text):
        return True, "I can only assist you with exploring our catalog and placing orders."

    return False, None

async def fetch_business_data_from_backend(business_id: str) -> dict:
    url = f"{BACKEND_SERVICE_URL}/businesses/{business_id}"
    headers = {"Authorization": f"Bearer {os.getenv('INTERNAL_SECRET')}"}
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

async def fetch_recent_history(customer_id: str, business_id: str) -> list:
    url = f"{BACKEND_SERVICE_URL}/chats/{business_id}/{customer_id}/recent"
    headers = {"Authorization": f"Bearer {os.getenv('INTERNAL_SECRET')}"}
    async with httpx.AsyncClient() as httpx_client:
        try:
            response = await httpx_client.get(url, headers=headers, timeout=3.0)
            if response.status_code == 200:
                return response.json() 
        except httpx.RequestError:
            pass
    return []

def format_history_for_openai(history: list, user_msg: str) -> list:
    formatted = []
    for msg in history:
        msg_role = msg.get("role") if isinstance(msg, dict) else msg.role
        msg_content = msg.get("content") if isinstance(msg, dict) else msg.content
        role = "assistant" if msg_role == "assistant" else "user"
        formatted.append({"role": role, "content": msg_content})
    formatted.append({"role": "user", "content": user_msg})
    return formatted

def format_history_for_gemini(history: list, user_msg: str) -> list:
    formatted = []
    for msg in history:
        msg_role = msg.get("role") if isinstance(msg, dict) else msg.role
        msg_content = msg.get("content") if isinstance(msg, dict) else msg.content
        role = "model" if msg_role == "assistant" else "user"
        formatted.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=msg_content)]
            )
        )
    formatted.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_msg)]
        )
    )
    return formatted

async def call_tier2_groq(openai_messages: list, system_instruction: str) -> str:
    url = "[https://api.groq.com/openapi/v1/chat/completions](https://api.groq.com/openapi/v1/chat/completions)"
    api_key = os.getenv("GROQ_API_KEY") 
    if not api_key:
        raise ValueError("Groq API Key missing")

    payload = {
        "model": "llama-3.1-8b-instant",
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
    url = "[https://openrouter.ai/api/v1/chat/completions](https://openrouter.ai/api/v1/chat/completions)"
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


@router.post("/bot", response_model=schemas.ChatResponse)
async def whatsapp_webhook(payload: schemas.ChatRequest, business_id: str):
    sanitized_message = sanitize_input(payload.message)
    if not sanitized_message:
        return schemas.ChatResponse(
            reply="It looks like your message was empty or contained unsupported formatting. What would you like to order?"
        )
    
    guardrail_triggered, guardrail_reply = check_guardrails(sanitized_message)
    if guardrail_triggered:
        return schemas.ChatResponse(reply=guardrail_reply)

    if re.search(r'\b(human|agent|support|talk to owner|help)\b', sanitized_message.lower()):
        return schemas.ChatResponse(
            reply="I'm flagging your question for the business owner right now. Hang tight!",
            action={"type": "HUMAN_HANDOFF"}
        )
    
    biz_task = fetch_business_data_from_backend(business_id)
    history_task = fetch_recent_history(payload.customerId, business_id)
    
    biz_data, recent_history = await asyncio.gather(biz_task, history_task)
    
    system_instruction = (
        f"You are PayMate AI, the store assistant for '{biz_data['name']}'.\n"
        f"Live Catalog:\n{biz_data['catalog']}\n\n"
        f"Review the conversation history to understand context. "
        f"If the user explicitly confirms they want to buy/checkout, calculate the exact total cost "
        f"and append this trigger code on a brand new line at the very end: [TRIGGER_PAYMENT: amount]"
    )

    openai_messages = format_history_for_openai(recent_history, sanitized_message)
    gemini_messages = format_history_for_gemini(recent_history, sanitized_message)

    ai_reply = None
    session_key = f"{payload.customerId}:{business_id}"

    if os.getenv("GEMINI_API_KEY"):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=gemini_messages,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                )
            )
            ai_reply = response.text
        except Exception as e:
            if "503" not in str(e) and "UNAVAILABLE" not in str(e).upper():
                raise HTTPException(status_code=500, detail=str(e))

    if not ai_reply:
        try:
            ai_reply = await call_tier2_groq(openai_messages, system_instruction)
        except Exception:
            pass

    if not ai_reply:
        try:
            ai_reply = await call_tier3_openrouter(openai_messages, system_instruction)
        except Exception:
            # Increment failure counter in memory mapping
            FAILURE_TRACKER[session_key] = FAILURE_TRACKER.get(session_key, 0) + 1
            
            if FAILURE_TRACKER[session_key] >= 3:
                return schemas.ChatResponse(
                    reply="I'm sorry, I am completely unavailable to take orders at the moment. Please try again later. Sorry for the inconvenience.",
                    action=None
                )
            
            return schemas.ChatResponse(
                reply="I couldn't process what you asked. Can you say that again?",
                action=None
            )

    # Reset failure counter on a successful AI generation response run
    FAILURE_TRACKER[session_key] = 0

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