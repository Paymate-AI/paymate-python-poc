import os
import logging
import uuid
from fastapi import HTTPException, status
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.exc import IntegrityError
from models.payment import Payment, VirtualAccount
from models.order import Order
from services.alatpay_service import ALATPayService
from services.order_service import OrderService
from services.product_service import ProductService
from datetime import datetime, timedelta, timezone


logger = logging.getLogger(__name__)

TS_SERVICE_URL = os.getenv("TS_SERVICE_URL")

class PaymentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.order_service = OrderService(db)
        self.product_service = ProductService(db)

    async def create_payment(self, order_id: int, amount: float) -> Payment:
        reference = str(uuid.uuid4())
        try:
            db_payment = Payment(
                order_id=order_id,
                amount=amount,
                reference=reference
            )
            self.db.add(db_payment)
            await self.db.commit()
            await self.db.refresh(db_payment, attribute_names=["virtual_account"])
            return db_payment
        except IntegrityError as e:
            await self.db.rollback()
            result = await self.db.execute(
            select(Payment)
            .where(Payment.order_id == order_id)
            .options(selectinload(Payment.virtual_account))
        )
            return result.scalars().first()
            

    async def generate_payment_virtual_account(self, payment_id: int, customer_whatsapp_id: str):
        result = await self.db.execute(
            select(Payment)
            .options(joinedload(Payment.virtual_account))
            .where(Payment.id == payment_id)
        )
        db_payment = result.scalars().first()
        if not db_payment:
            raise ValueError("Payment not found")

        if db_payment.virtual_account:
            logger.info("Virtual account already exists for payment %s", payment_id)
            return {
                "account_number": db_payment.virtual_account.account_number,
                "bank_name": db_payment.virtual_account.bank_name,
                "reference": db_payment.reference,
                "transaction_id": db_payment.transaction_id or "",
                "expiry_minutes": 60,
            }

        # Call ALATPay to generate virtual account
        alatpay_response = await ALATPayService.generate_virtual_account(
            order_id=db_payment.order_id,
            amount=db_payment.amount,
            reference=db_payment.reference,
            customer_whatsapp_id=customer_whatsapp_id
        )
        db_payment.transaction_id = alatpay_response.pop("transaction_id")
        # Create virtual account record
        expiry_date = datetime.now() + timedelta(minutes=alatpay_response.get("expiry_minutes", 60))
        try:
            db_virtual_account = VirtualAccount(
                payment_id=payment_id,
                account_number=alatpay_response["account_number"],
                account_name="Paymate Ai",
                bank_name=alatpay_response["bank_name"],
                expiry_date=expiry_date
            )
            self.db.add(db_virtual_account)
            await self.db.commit()
            await self.db.refresh(db_payment)
        except IntegrityError as e:
            await self.db.rollback()
            logger.error("Failed to persist virtual account for payment %s: %s", payment_id, e, exc_info=True)
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error("Unexpected error while persisting virtual account for payment %s: %s", payment_id, e, exc_info=True)
            raise
        logger.info(f"geen --- {alatpay_response}")
        return alatpay_response

    async def verify_and_update_payment(self, reference: str) -> Payment | None:
        result = await self.db.execute(
            select(Payment)
            .options(joinedload(Payment.order).joinedload(Order.items))
            .where(Payment.reference == reference)
        )
        db_payment = result.scalars().first()
        if not db_payment:
            return None

        # Verify with ALATPay
        try:
            now = datetime.now(timezone.utc)
            # 2. Establish the cutoff threshold (24 hours ago)
            cutoff_time = now - timedelta(days=1)
            created_at = db_payment.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            verification = await ALATPayService.verify_payment(db_payment.transaction_id)
            if verification["status"] == "successful":
                logger.info(f"Payment verification called for reference: {reference}")
                db_payment.status = "successful"
                db_payment.gateway_response = str(verification)
                order = db_payment.order
                # Update order status
                await self.order_service.update_order_status(db_payment.order_id, "paid")

                # Update inventory in the TS service catalog
                for item in order.items:
                    await self.product_service.update_stock(item.product_id, item.quantity, "subtract")

            elif verification["status"] == "failed":
                db_payment.status = "failed"
                db_payment.gateway_response = str(verification)
        except HTTPException as e:
            if e.detail.get("status") is False and created_at < cutoff_time:
                db_payment.status = "Failed"
        except Exception as e:
            logger.error(f"Unexpected error verifying {reference}: {e}")

        await self.db.commit()
        await self.db.refresh(db_payment)
        return db_payment

    async def get_payment_by_reference(self, reference: str) -> Payment | None:
        result = await self.db.execute(select(Payment).where(Payment.reference == reference))
        return result.scalars().first()

    async def get_pending_payments(self) -> list[Payment]:
        result = await self.db.execute(select(Payment).where(Payment.status == "pending"))
        return result.scalars().all()
    
    async def get_pending_payments_with_orders(self) -> list[Payment]:
        result = await self.db.execute(
            select(Payment)
            .options(joinedload(Payment.order))
            .where(Payment.status == "pending")
        )
        return result.scalars().all()
    
    async def send_payment_update_to_user(self, customer_id, message):
        whatsappToken = os.getenv.WHATSAPP_TOKEN
        phoneNumberId = os.getenv.PHONE_NUMBER_ID

        if (not whatsappToken or not phoneNumberId) :
            raise HTTPException(status_code=status.HTTP_202_ACCEPTED, detail='Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID in environment variables')
        
        headers = {
            "Authorization": f'Bearer {whatsappToken}',
            "Content-Type": "application/json"
        }

        url = f'https://graph.facebook.com/v25.0/{phoneNumberId}/messages'


        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': customer_id,
            'type': 'text',
            'text': {
            'preview_url': False,
            'body': message,
            },
        }

        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                logger.info(f"message sent to customer with id {customer_id}")
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error: {e.response.text}")
                
