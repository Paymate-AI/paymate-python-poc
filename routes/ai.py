import os
import re
import httpx
import inspect
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
async def whatsapp_webhook(
    payload: schemas.ChatRequest, 
    business_id: str,
    db: Session = Depends(get_db)
):
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
        """
        Retrieve the details of the current business store, such as name, operational info, or active settings.
        """
        try:
            # Assuming BusinessService exposes your business methods
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

                # Include other relevant attributes from your Business model if needed
            }
        except Exception as e:
            return {"status": "error", "message": f"Error retrieving business details: {str(e)}"}

    def search_products(query: str = "") -> dict:
        """
        Search for available products in the store's inventory and get their prices and stock availability.
        
        Args:
            query: Optional search term to filter products by name or description.
        """
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
        """
        Place an order for products for the store.
        
        Args:
            items: A list of dicts, each containing 'product_id' (int) and 'quantity' (int).
            customer_name: Optional name of the customer placing the order.
        """
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
        """
        Generate a virtual bank account via ALATPay for the customer to transfer payment for an order.
        
        Args:
            order_id: The integer ID of the order.
        """
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
        """
        Verify the status of a payment using the payment reference. If no reference is provided, it will check the latest pending payment for this business.
        
        Args:
            reference: Optional unique payment reference string.
        """
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

    # Prepare message blocks based on API formats
    openai_messages = format_history_for_openai(payload.history, payload.message)
    gemini_messages = format_history_for_gemini(payload.history, payload.message)

    ai_reply = None

    # TIER 1: Gemini
    if os.getenv("GEMINI_API_KEY"):
        try:
            max_turns = 5
            current_turn = 0
            current_messages = list(gemini_messages)
            tools_list = [get_business_details, search_products, place_order, create_payment_virtual_account, verify_payment_status]

            # We start the loop
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
                
                # Append model content containing function calls
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
                        result = {"status": "error", "message": f"Invalid arguments for {name}: {str(te)}. Please supply required parameters."}
                    except Exception as ex:
                        result = {"status": "error", "message": f"Failed to execute {name}: {str(ex)}"}
                    
                    response_parts.append(
                        types.Part.from_function_response(
                            name=name,
                            response={"result": result}
                        )
                    )
                
                current_messages.append(
                    types.Content(
                        role="user",
                        parts=response_parts
                    )
                )

                response = client.models.generate_content(
                    model='gemini-3.5-flash',
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

    # TIER 2: Groq (Fallback)
    if not ai_reply:
        try:
            ai_reply = await call_tier2_groq(openai_messages, system_instruction)
        except Exception:
            pass

    # TIER 3: OpenRouter (Fallback)
    if not ai_reply:
        try:
            ai_reply = await call_tier3_openrouter(openai_messages, system_instruction)
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"All layers offline: {str(e)}")

    return schemas.ChatResponse(reply=ai_reply, action=action_payload)