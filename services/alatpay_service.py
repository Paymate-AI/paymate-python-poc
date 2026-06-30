import os
import httpx
from dotenv import load_dotenv

load_dotenv()


class ALATPayService:
    BASE_URL = os.getenv("ALATPAY_BASE_URL", "https://api.alatpay.ng")
    API_KEY = os.getenv("ALATPAY_API_KEY", "")
    MERCHANT_ID = os.getenv("ALATPAY_MERCHANT_ID", "")

    @staticmethod
    async def generate_virtual_account(amount: float, reference: str, customer_name: str, email: str = "") -> dict:
        """Generate virtual account number via ALATPay API"""
        # This is a placeholder - replace with actual ALATPay API integration
        # For now, we'll simulate the response
        return {
            "account_number": "1234567890",
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
