import os
from fastapi import HTTPException
import httpx
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, retry_if_exception_type, retry_if_not_exception_type

load_dotenv()


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
        )
    )
    async def generate_virtual_account(order_id: int, amount: float, reference: str, customer_name: str, ) -> dict:
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
            "orderId": order_id,
            "description": "ALATPay Checkout Payment",
            "customer": {
                "name": customer_name
            }
        }

        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.post(url, headers=headers, json=payload, timeout=10.0)
                response.raise_for_status()  # Raise HTTP errors
                alat_response = response.json()
            except httpx.HTTPStatusError as e:
                print(f"HTTP error: {e}")
                if e.response.status_code == 400:
                    # Stop immediately for Bad Request
                    raise BadRequestError("Bad Request to ALATPay API") from e
                raise  # Re-raise other HTTP errors to retry
            except httpx.RequestError as e:
                print(f"Request error: {e}")
                raise  # Re-raise to retry

        return {
            "account_number": alat_response["data"].get("virtualBankAccountNumber", ""),
            "account_name": customer_name,
            "bank_name": "Wema Bank",
            "reference": reference,
            "expiry_minutes": 60
        }

    @staticmethod
    async def verify_payment(reference: str) -> dict:
        """Verify payment status via ALATPay API"""
        # This is a placeholder - replace with actual ALATPay API integration
        # For now, we'll return a simulated successful payment
        return {
            "status": "successful",
            "reference": reference,
            "amount": 1000.0,
            "currency": "NGN"
        }
