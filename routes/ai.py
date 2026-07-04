import os
import re
import httpx
import inspect
import asyncio
from fastapi import HTTPException, status, APIRouter, Depends
from sqlalchemy.orm import Session
from database.config import get_db
from google import genai
from google.genai import types
import schemas
from services.product_service import ProductService
from services.order_service import OrderService
from services.payment_service import PaymentService
from services.alatpay_service import BadRequestError
from services.business_service import BusinessService

router = APIRouter()
client = genai.Client()

BACKEND_SERVICE_URL = os.getenv("BACKEND_SERVICE_URL", "http://localhost:8000/api")

FAILURE_TRACKER = {}

# ----------------------------------------------------------------
# GUARDRAIL & SANITIZATION UTILITIES
# ----------------------------------------------------------------
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

# ----------------------------------------------------------------
# CONTEXT & HISTORY UTILITIES
# ----------------------------------------------------------------
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
    business_id: str,
    db: Session = Depends(get_db)
):
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
    
    business_service = BusinessService(db)
    biz_data = business_service.get_business_by_id(business_id)
    if not biz_data:
        return schemas.ChatResponse(
            reply="Sorry, I can't find the business you're talking to. Please try again."
        )
    
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
            biz_service = BusinessService(db) 
            business = biz_service.get_business_by_id(business_id=business_id)
            if not business:
                return {"status": "error", "message": f"Business with ID {business_id} not found."}
            return {
                "business_id": business.id,
                "name": business.name,
                "service": business.service,
                "state": business.state,
                "city": business.city,
                "address": business.address,
                "phone": business.phone,
            }
        except Exception as e:
            return {"status": "error", "message": f"Error retrieving business details: {str(e)}"}

    def search_products(query: str = "") -> dict:
        try:
            prod_service = ProductService(db)
            products = prod_service.get_available_products(business_id=business_id)
            if query:
                q = query.lower()
                products = [p for p in products if q in p.name.lower() or (p.description and q in p.description.lower())]
            return {
                "products": [
                    {
                        "product_id": p.id,
                        "name": p.name,
                        "description": p.description,
                        "price": p.price,
                        "stock_quantity": p.stock_quantity
                    } for p in products
                ]
            }
        except Exception as e:
            return {"status": "error", "message": f"Error searching products: {str(e)}"}

    def place_order(items: list[dict], customer_name: str = "Customer") -> dict:
        from schemas.order import OrderCreate, OrderItemCreate
        try:
            order_items = [
                OrderItemCreate(product_id=int(item["product_id"]), quantity=int(item["quantity"]))
                for item in items
            ]
            order_data = OrderCreate(
                business_id=business_id,
                customer_name=customer_name,
                items=order_items
            )
            order_service = OrderService(db)
            order = order_service.create_order(order_data)
            return {
                "status": "success",
                "order_id": order.id,
                "total_amount": order.total_amount,
                "order_status": order.status,
                "message": f"Order {order.id} placed successfully. Total amount is NGN {order.total_amount}."
            }
        except ValueError as e:
            return {"status": "error", "message": str(e)}
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
                "business_name": biz_data.name,
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

    # --- SWAPPED FOR DB SESSION RESOLUTION ---
    # openai_messages = format_history_for_openai(payload.history, sanitized_message)
    # gemini_messages = format_history_for_gemini(payload.history, sanitized_message)
    
    recent_history = await fetch_recent_history(payload.customerId, business_id)
    openai_messages = format_history_for_openai(recent_history, sanitized_message)
    gemini_messages = format_history_for_gemini(recent_history, sanitized_message)
    # -----------------------------------------------------------------------

    ai_reply = None
    session_key = f"{payload.customerId}:{business_id}"

    if os.getenv("GEMINI_API_KEY"):
        try:
            max_turns = 5
            current_turn = 0
            current_messages = list(gemini_messages)
            tools_list = [get_business_details, search_products, place_order, create_payment_virtual_account, verify_payment_status]

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

    FAILURE_TRACKER[session_key] = 0
    return schemas.ChatResponse(reply=ai_reply, action=action_payload)