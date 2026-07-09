import logging
import os
from fastapi import HTTPException, status
import httpx
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, retry_if_exception_type, retry_if_not_exception_type

load_dotenv()

logger = logging.getLogger(__name__)


# Custom exception for Bad Request (400) that we don't want to retry
class BadRequestError(Exception):
    pass


class ALATPayService:
    BASE_URL = os.getenv("ALATPAY_BASE_URL", "https://api.alatpay.ng")
    API_KEY = os.getenv("ALATPAY_API_KEY", "")
    MERCHANT_ID = os.getenv("ALATPAY_MERCHANT_ID", "")

    @staticmethod
    @retry(
        stop=stop_after_attempt(3),  # Retry up to 3 times total
        retry=(
            retry_if_exception_type(httpx.RequestError) |
            retry_if_exception_type(httpx.HTTPStatusError) &
            retry_if_not_exception_type(BadRequestError)
        ),
        reraise=True
    )
    async def generate_virtual_account(order_id: int, amount: float, reference: str, customer_whatsapp_id: str, ) -> dict:
        """Generate virtual account number via ALATPay API with retries"""
        url = f"{ALATPayService.BASE_URL}/bank-transfer/api/v1/bankTransfer/virtualAccount"
        headers = {
            "Ocp-Apim-Subscription-Key": ALATPayService.API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "businessId": ALATPayService.MERCHANT_ID,
            "amount": amount,
            "currency": "NGN",
            "orderId": str(order_id),
            "description": "ALATPay Checkout Payment",
            "customer": {
                "whatsapp_id": customer_whatsapp_id
            }
        }

        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.post(url, headers=headers, json=payload, timeout=10.0)
                response.raise_for_status()  # Raise HTTP errors
                alat_response = response.json()["data"]
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error: {e.response.text}")
                if e.response.status_code == 400 or e.response.status_code == 422:
                    # Stop immediately for Bad Request
                    raise BadRequestError(e.response.json()["message"]) from e
                raise  # Re-raise other HTTP errors to retry
            except httpx.RequestError as e:
                logger.error(f"Request error: {e}")
                raise  # Re-raise to retry

        return {
            "account_number": alat_response.get("virtualBankAccountNumber", ""),
            "customer_whatsapp_id": customer_whatsapp_id,
            "bank_name": "Wema Bank",
            "reference": reference,
            "transaction_id": alat_response.get("transactionId", ""),
            "expiry_minutes": 60
        }

    @staticmethod
    @retry(
        stop=stop_after_attempt(3),  # Retry up to 3 times total
        retry=(
            retry_if_exception_type(httpx.RequestError) |
            retry_if_exception_type(httpx.HTTPStatusError) &
            retry_if_not_exception_type(BadRequestError)
        ),
        reraise=True
    )

    async def verify_payment(transaction_id: str) -> dict:
        """Verify payment status via ALATPay API using the transaction ID"""
        if not transaction_id:
            raise ValueError("transaction_id is required to verify a payment")

        # ALATPay requires businessId as a query parameter
        url = f"{ALATPayService.BASE_URL}/bank-transfer/api/v1/bankTransfer/transactions/{transaction_id}"
        params = {"businessId": ALATPayService.MERCHANT_ID}
        headers = {
            "Ocp-Apim-Subscription-Key": ALATPayService.API_KEY,
            "Content-Type": "application/json"
        }
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.get(url, params=params, headers=headers, timeout=10.0)
                if response.status_code == 200:
                    alat_response = response.json()
                else:
                    logger.error(f"HTTP error: {response.text}")
                    error = {
                        "status": response.json().get("status"),
                        "message": response.json().get("message")
                    }
                    raise HTTPException(status_code=status.HTTP_202_ACCEPTED, detail=error)
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error: {e.response.text}")
                if e.response.status_code == 400 or e.response.status_code == 422:
                    raise BadRequestError("Bad Request to ALATPay API") from e
                raise
            except httpx.RequestError as e:
                logger.error(f"Request error: {e}")
                raise

        data = alat_response.get("data") or {}
        return {
            "status": data.get("paymentStatus", "pending"),
            "reference": data.get("reference", ""),
            "amount": float(data.get("amount", 0)),
            "currency": data.get("currency", ""),
            "customer": data.get("customer", ""),
            "order_id": data.get("orderId", ""),
            "description": data.get("description", "")
        }
