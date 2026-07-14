import os
import re
import httpx
import inspect
import asyncio
from typing import Optional
from fastapi import HTTPException, status, APIRouter, Depends
from sqlalchemy.orm import Session
from database.config import get_db
from google import genai
from google.genai import types
import schemas
from services.order_service import OrderService
from services.payment_service import PaymentService
from services.alatpay_service import BadRequestError

router = APIRouter()

# --- DYNAMIC CLIENT INITIALIZATION FOR BOTH OF YOU ---
GCP_PROJECT = os.getenv("GCP_PROJECT_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

if GCP_PROJECT:
    client = genai.Client(
        vertexai=True,
        project=GCP_PROJECT,
        location=os.getenv("GCP_REGION", "us-central1")
    )
elif GEMINI_KEY:
    client = genai.Client(api_key=GEMINI_KEY)
else:
    client = None
# -----------------------------------------------------

TS_SERVICE_URL = os.getenv("TS_SERVICE_URL", "http://localhost:8000/api")
FAILURE_TRACKER = {}

# ----------------------------------------------------------------
# GUARDRAIL & SANITIZATION UTILITIES
# ----------------------------------------------------------------
def sanitize_input(text_str: str) -> str:
    if not text_str:
        return ""
    text_str = re.sub(r'<[^>]*>', '', text_str)
    text_str = text_str.replace("```", "").replace("`", "")
    text_str = re.sub(r'[\*\_~#\-]', '', text_str)
    text_str = re.sub(r'[\[\]\{\}]', '', text_str)
    return " ".join(text_str.split())

def check_guardrails(text_str: str) -> tuple[bool, str | None]:
    clean_text = text_str.lower()
    insult_pattern = r'\b(stupid|idiot|fool|useless|bastard|mad|craze|mumu|maggot|fuck|shattered|trash|foolish)\b'
    if re.search(insult_pattern, clean_text):
        return True, "Let's keep things professional. Please let me know how I can help with your order."
        
    manipulation_pattern = r'\b(system prompt|ignore previous|act as|you are now|developer mode|override|ignore previous instructions|send money)\b'
    if re.search(manipulation_pattern, clean_text):
        return True, "I can only assist you with exploring our catalog and placing orders."

    return False, None

# ----------------------------------------------------------------
# CONTEXT & HISTORY UTILITIES
# ----------------------------------------------------------------
async def fetch_business_data_from_backend(business_id: str) -> dict:
    url = f"{TS_SERVICE_URL}/businesses/{business_id}"
    headers = {"X-Internal-Secret": os.getenv("INTERNAL_SECRET")}
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

def format_history_for_openai(history: list, user_msg: str) -> list:
    formatted = []
    history_to_format = list(history)
    has_latest = False
    if history_to_format:
        last_msg = history_to_format[-1]
        last_role = last_msg.get("role") if isinstance(last_msg, dict) else last_msg.role
        if last_role == "user":
            has_latest = True
            
    for msg in history_to_format:
        msg_role = msg.get("role") if isinstance(msg, dict) else msg.role
        msg_content = msg.get("content") if isinstance(msg, dict) else msg.content
        role = "assistant" if msg_role == "assistant" else "user"
        formatted.append({"role": role, "content": msg_content})
        
    if not has_latest:
        formatted.append({"role": "user", "content": user_msg})
    return formatted

def format_history_for_gemini(history: list, user_msg: str) -> list:
    formatted = []
    history_to_format = list(history)
    has_latest = False
    if history_to_format:
        last_msg = history_to_format[-1]
        last_role = last_msg.get("role") if isinstance(last_msg, dict) else last_msg.role
        if last_role == "user":
            has_latest = True
            
    for msg in history_to_format:
        msg_role = msg.get("role") if isinstance(msg, dict) else msg.role
        msg_content = msg.get("content") if isinstance(msg, dict) else msg.content
        role = "model" if msg_role == "assistant" else "user"
        formatted.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=msg_content)]
            )
        )
        
    if not has_latest:
        formatted.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_msg)]
            )
        )
    return formatted


def extract_action_from_text(text: str) -> tuple[str, dict | None]:
    if not text:
        return "", None

    # Try to find a JSON block in the text
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        try:
            import json
            action_data = json.loads(json_match.group(0))
            # Validate that it has the expected format
            if isinstance(action_data, dict) and "type" in action_data:
                # Remove the JSON string from the user-facing reply so they don't see raw JSON in WhatsApp
                clean_text = text.replace(json_match.group(0), "").strip()
                # Clean up any surrounding quotes/markdown from the text
                clean_text = re.sub(r'```json\s*```', '', clean_text).strip()
                clean_text = re.sub(r'```\s*```', '', clean_text).strip()
                clean_text = clean_text.strip("`").strip()
                return clean_text, action_data
        except Exception:
            pass
    return text, None


# ----------------------------------------------------------------
# MULTI-TIER AI EXECUTORS WITH HISTORY
# ----------------------------------------------------------------
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


# ----------------------------------------------------------------
# ENDPOINT GATEWAY
# ----------------------------------------------------------------
@router.post("/bot", response_model=schemas.ChatResponse)
async def whatsapp_webhook(
    payload: schemas.ChatRequest, 
    business_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    # TODO : Check if the headers contains the valid secret key 
    sanitized_message = sanitize_input(payload.message)
    if not sanitized_message:
        return schemas.ChatResponse(
            reply="It looks like your message was empty or contained unsupported formatting. What would you like to order?"
        )
    
    guardrail_triggered, guardrail_reply = check_guardrails(sanitized_message)
    if guardrail_triggered:
        return schemas.ChatResponse(reply=guardrail_reply)

    if not sanitized_message:
        return schemas.ChatResponse(
            reply="I'm flagging your question for the business owner right now. Hang tight!",
            action={"type": "HUMAN_HANDOFF"}
        )
    
    # Fetch business data via internal TS API
    biz_data = None
    if business_id and business_id != "None":
        try:
            ts_base_url = TS_SERVICE_URL.replace("/api", "")
            headers = {"Authorization": f"Bearer {os.getenv('INTERNAL_SECRET', '')}"}
            with httpx.Client() as client_http:
                resp = client_http.get(f"{ts_base_url}/internal/business/{business_id}", headers=headers, timeout=10.0)
                if resp.status_code == 200:
                    from types import SimpleNamespace
                    biz_data = SimpleNamespace(**resp.json())
        except Exception as e:
            print(f"Error fetching business details from TS: {e}")
    
    # Determine the conversational state context
    state = payload.state or ("CUSTOMER_BROWSING" if business_id and business_id != "None" else "INTENT_SELECTION")

    # If in CUSTOMER_BROWSING state, a business must exist
    if state == "CUSTOMER_BROWSING" and not biz_data:
        return schemas.ChatResponse(
            reply="Sorry, I can't find the business you're talking to. Please try again."
        )
    
    # Determine system instruction based on session state
    if state == "KYC_NAME":
        system_instruction = (
            "You are the PayMate onboarding assistant. The user is currently in the KYC name collection flow.\n"
            "Your task is to extract the user's full name from their input.\n"
            "If they provided a name (e.g., 'Divine', 'My name is Divine', etc.), extract the clean name and return it using the action payload format:\n"
            '{"type": "SET_KYC_NAME", "payload": {"name": "<extracted name>"}}\n'
            "In your reply, say something welcoming and confirm you've got their name, then ask for their email (e.g., 'Nice to meet you, Divine! What is your email address?').\n"
            "If they didn't provide a valid name or their input is unclear, politely ask them to state their name clearly."
        )
    elif state == "KYC_EMAIL":
        user_name = payload.data.get("name", "there") if payload.data else "there"
        system_instruction = (
            "You are the PayMate onboarding assistant. The user is currently in the KYC email collection flow.\n"
            f"The user's name is '{user_name}'. You MUST address the user by this name in your responses.\n"
            "Your task is to extract the user's email address from their input.\n"
            "If they provided an email (e.g., 'my email is divine@example.com', 'divine@example.com', etc.), extract it.\n\n"
            "Additionally, look at the very beginning of the chat history (the first user message before name/email questions).\n"
            "If the user initially expressed a specific intent (like wanting to buy products, search for a shop, register a business, or manage a catalog):\n"
            f"- You MUST acknowledge that intent AND transition the user in a SINGLE message. Rules:\n"
            f"  * If they want to register a business: your reply MUST be a single message that confirms they are set up AND asks for their business name. "
            f"Use EXACTLY this format: 'You are all set, {user_name}! I can see you wanted to register a business — let\\'s get that set up. What is the name of your business?'\n"
            f"  * If they want to search, buy, or browse products (e.g., 'I want to buy shoes', 'I want to buy shoes from shop XYZ'), say: 'You are all set, {user_name}! Let me find those products for you...'\n"
            "- Return the action with a 'next_command' in the payload:\n"
            "  * If they want to register a business: {\"type\": \"SET_KYC_EMAIL\", \"payload\": {\"email\": \"<extracted email>\", \"next_command\": \"register_business\"}}\n"
            "  * If they want to search or buy products, infer the product search term (e.g., 'shoes') and any shop/business code (e.g., 'XYZ' or null) and return:\n"
            "    {\"type\": \"SET_KYC_EMAIL\", \"payload\": {\"email\": \"<extracted email>\", \"next_command\": \"search_product\", \"search_query\": \"<inferred product name>\", \"business_code\": \"<inferred business code or null>\"}}\n"
            "  * If they want to manage catalog: {\"type\": \"SET_KYC_EMAIL\", \"payload\": {\"email\": \"<extracted email>\", \"next_command\": \"manage_catalog\"}}\n"
            f"If they did not express any specific intent initially, just reply confirming they are set up (e.g., 'You are all set, {user_name}!'), and return:\n"
            '  {"type": "SET_KYC_EMAIL", "payload": {"email": "<extracted email>"}}\n\n'
            "If they didn't provide a valid email, politely ask them to try again with a valid email address."
        )
    elif state == "INTENT_SELECTION":
        biz_name_part = f" for '{biz_data.name}'" if biz_data else ""
        system_instruction = (
            f"You are PayMate AI, the platform concierge and store assistant{biz_name_part}.\n"
            "You have context on all administrative and catalog commands valid in the main menu:\n"
            "- register_business: Start the onboarding flow to set up/register a new business.\n"
            "- find_service: Find, browse, or search for other stores/services (e.g., if a user wants to buy something, browse shops, or find products).\n"
            "- manage_catalog: Open the menu to add, remove, or view items in their business catalog.\n"
            "- delete_business: Trigger the business deletion workflow.\n"
            "- main_menu: Go back to the main menu.\n\n"
            "Analyze the user's input to determine their intent:\n"
            "1. If they express intent to buy products, search for a shop, or browse goods (e.g. 'I want to buy shoes', 'search for shoes from XYZ', etc.):\n"
            "   Acknowledge that you are searching/finding it for them, infer the product search query (e.g. 'shoes') and any shop/business code (e.g. 'XYZ' or null), and return the action payload:\n"
            "   {\"type\": \"SEARCH_PRODUCT\", \"payload\": {\"query\": \"<inferred product query>\", \"business_code\": \"<inferred business code or null>\"}}\n"
            "2. If they just say they want to find stores or browse shops generally without a product name (e.g., 'find a store', 'show me shops'):\n"
            "   Respond politely saying you will trigger the service finder, and return the action payload:\n"
            "   {\"type\": \"TRIGGER_COMMAND\", \"payload\": {\"command\": \"find_service\"}}\n"
            "3. If they want to register or set up a business (e.g. 'register my store', 'sell on paymate', etc.), "
            "respond saying you will start registration, and return the action payload:\n"
            '{"type": "TRIGGER_COMMAND", "payload": {"command": "register_business"}}\n'
            "4. If they want to manage their store catalog generally (e.g. 'manage catalog'), "
            "respond saying you are opening catalog manager, and return the action payload:\n"
            '{"type": "TRIGGER_COMMAND", "payload": {"command": "manage_catalog"}}\n'
            "  - If they explicitly want to add a product or item (e.g. 'add item', 'add product', 'new product'), "
            "return the action payload:\n"
            '{"type": "TRIGGER_COMMAND", "payload": {"command": "add_item"}}\n'
            "  - If they explicitly want to remove a product or item (e.g. 'remove item', 'delete product'), "
            "return the action payload:\n"
            '{"type": "TRIGGER_COMMAND", "payload": {"command": "remove_item"}}\n'
            "  - If they explicitly want to view their catalog (e.g. 'view catalog', 'show products'), "
            "return the action payload:\n"
            '{"type": "TRIGGER_COMMAND", "payload": {"command": "view_catalog"}}\n'
            "5. If they want to delete their business (e.g. 'delete my business'), "
            "respond saying you are initiating deletion, and return the action payload:\n"
            '{"type": "TRIGGER_COMMAND", "payload": {"command": "delete_business"}}\n'
            "6. If they are just chatting or greeting you, respond contextually to guide them about the options available."
        )
    else: # CUSTOMER_BROWSING
        system_instruction = (
            f"You are PayMate AI, the store assistant for '{biz_data.name}'.\n"
            f"You have access to tools/functions to look up business information, search for products, place orders, create virtual accounts, and verify payment statuses.\n"
            f"Always use the appropriate tools to look up business and product details, submit orders, and obtain payment details. Do not guess or fabricate information.\n"
            f"When an order is created, tell the customer the order ID and amount, and then ask or offer to create a virtual payment account.\n"
            f"When a payment virtual account is created, present the bank name, account number, account name, amount, and the payment_reference clearly to the customer."
        )

    action_payload = None

    def get_business_details() -> dict:
        try:
            ts_base_url = TS_SERVICE_URL.replace("/api", "")
            headers = {"Authorization": f"Bearer {os.getenv('INTERNAL_SECRET', '')}"}
            with httpx.Client() as client_http:
                resp = client_http.get(f"{ts_base_url}/internal/business/{business_id}", headers=headers, timeout=10.0)
                if resp.status_code == 200:
                    return resp.json()
                return {"status": "error", "message": "Business not found."}
        except Exception as e:
            return {"status": "error", "message": f"Error retrieving business details: {str(e)}"}

    def search_products(query: str = "") -> dict:
        try:
            ts_base_url = TS_SERVICE_URL.replace("/api", "")
            headers = {"Authorization": f"Bearer {os.getenv('INTERNAL_SECRET', '')}"}
            with httpx.Client() as client_http:
                resp = client_http.get(
                    f"{ts_base_url}/internal/business/{business_id}/products",
                    params={"query": query},
                    headers=headers,
                    timeout=10.0
                )
                if resp.status_code == 200:
                    return {"products": resp.json()}
                return {"products": []}
        except Exception as e:
            return {"status": "error", "message": f"Error searching products: {str(e)}"}

    def place_order(items: list[dict], customer_name: str = "Customer") -> dict:
        try:
            ts_base_url = TS_SERVICE_URL.replace("/api", "")
            headers = {"Authorization": f"Bearer {os.getenv('INTERNAL_SECRET', '')}"}
            payload_data = {
                "business_id": business_id,
                "customer_name": customer_name,
                "items": [
                    {"product_id": str(item["product_id"]), "quantity": int(item["quantity"])}
                    for item in items
                ]
            }
            with httpx.Client() as client_http:
                resp = client_http.post(
                    f"{ts_base_url}/internal/orders",
                    json=payload_data,
                    headers=headers,
                    timeout=10.0
                )
                if resp.status_code == 200:
                    order = resp.json()
                    return {
                        "status": "success",
                        "order_id": order["id"],
                        "total_amount": order["total_amount"],
                        "order_status": order["status"],
                        "message": f"Order {order['id']} placed successfully. Total amount is NGN {order['total_amount']}."
                    }
                return {"status": "error", "message": resp.text}
        except Exception as e:
            return {"status": "error", "message": f"Failed to place order: {str(e)}"}

    async def create_payment_virtual_account(order_id: int) -> dict:
        nonlocal action_payload
        try:
            order_service = OrderService(db)
            order = order_service.get_order(order_id)
            if not order:
                return {"status": "error", "message": f"Order with ID {order_id} not found."}
            
            payment_service = PaymentService(db)
            payment = payment_service.create_payment(order_id, order.total_amount)
            
            if payment.virtual_account:
                account_data = {
                    "account_number": payment.virtual_account.account_number,
                    "account_name": payment.virtual_account.account_name,
                    "bank_name": payment.virtual_account.bank_name,
                    "expiry_minutes": 60
                }
            else:
                account_data = await payment_service.generate_payment_virtual_account(
                    payment.id,
                    order.customer_name or "Customer"
                )
                
            action_payload = {
                "type": "COLLECT_PAYMENT",
                "amount": int(payment.amount),
                "business_name": biz_data.name if biz_data else "Store",
                "payment_reference": payment.reference
            }
            
            return {
                "status": "success",
                "payment_reference": payment.reference,
                "account_number": account_data["account_number"],
                "account_name": account_data["account_name"],
                "bank_name": account_data["bank_name"],
                "amount": payment.amount,
                "currency": "NGN"
            }
        except BadRequestError as e:
            return {"status": "error", "message": "Invalid request to generate virtual account"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to generate virtual account: {str(e)}"}

    async def verify_payment_status(reference: str = None) -> dict:
        nonlocal action_payload
        try:
            payment_service = PaymentService(db)
            if not reference:
                from models.payment import Payment
                from models.order import Order
                latest_pending = (
                    db.query(Payment)
                    .join(Order)
                    .filter(Order.business_id == business_id)
                    .filter(Payment.status == "pending")
                    .order_by(Payment.created_at.desc())
                    .first()
                )
                if latest_pending:
                    reference = latest_pending.reference
                else:
                    return {"status": "error", "message": "No pending payment found to verify."}

            payment = await payment_service.verify_and_update_payment(reference)
            if not payment:
                return {"status": "error", "message": f"Payment with reference {reference} not found."}
            
            if payment.status == "successful":
                action_payload = {
                    "type": "PAYMENT_SUCCESSFUL",
                    "order_id": payment.order_id,
                    "amount": payment.amount,
                    "payment_reference": payment.reference
                }
                
            return {
                "status": "success",
                "payment_reference": payment.reference,
                "payment_status": payment.status,
                "order_id": payment.order_id,
                "amount": payment.amount
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to verify payment: {str(e)}"}

    # Use history passed in from TS service (already includes current user message)
    openai_messages = format_history_for_openai(payload.history, sanitized_message)
    gemini_messages = format_history_for_gemini(payload.history, sanitized_message)

    ai_reply = None
    session_key = f"{payload.customerId}:{business_id}"

    print(f"DEBUG BOT: client={client is not None}, state={state}, business_id={business_id}")
    print(f"DEBUG GEMINI MESSAGES: {gemini_messages}")

    if client:
        try:
            max_turns = 5
            current_turn = 0
            current_messages = list(gemini_messages)
            tools_list = [get_business_details, search_products, place_order, create_payment_virtual_account, verify_payment_status] if state not in ["KYC_NAME", "KYC_EMAIL", "INTENT_SELECTION"] else None

            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=current_messages,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    tools=tools_list,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                )
            )

            while response.function_calls and current_turn < max_turns:
                current_turn += 1
                if response.candidates and response.candidates[0].content:
                    current_messages.append(response.candidates[0].content)
                
                response_parts = []
                for call in response.function_calls:
                    name = call.name
                    args = call.args
                    
                    try:
                        if name == "search_products":
                            result = search_products(**args)
                        elif name == "place_order":
                            result = place_order(**args)
                        elif name == "create_payment_virtual_account":
                            result = await create_payment_virtual_account(**args)
                        elif name == "verify_payment_status":
                            result = await verify_payment_status(**args)
                        else:
                            result = {"status": "error", "message": f"Unknown tool: {name}"}
                    except TypeError as te:
                        result = {"status": "error", "message": f"Invalid arguments for {name}: {str(te)}."}
                    except Exception as ex:
                        result = {"status": "error", "message": f"Failed to execute {name}: {str(ex)}"}
                    
                    response_parts.append(
                        types.Part.from_function_response(
                            name=name,
                            response={"result": result}
                        )
                    )
                
                current_messages.append(types.Content(role="user", parts=response_parts))

                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=current_messages,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.2,
                        tools=tools_list,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                    )
                )

            print(f"DEBUG GEMINI RESPONSE: candidates={response.candidates}, text={repr(response.text)}")
            ai_reply = response.text
        except Exception as e:
            print(f"DEBUG GEMINI EXCEPTION ({type(e).__name__}): {e}")
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

    # Clean the reply and extract action payload if present in the text response
    ai_reply, extracted_action = extract_action_from_text(ai_reply)
    if extracted_action:
        action_payload = extracted_action

    FAILURE_TRACKER[session_key] = 0
        
    return schemas.ChatResponse(reply=ai_reply, action=action_payload)