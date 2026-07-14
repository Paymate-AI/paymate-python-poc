import logging
import uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
from models.payment import Payment, VirtualAccount
from models.order import Order
from services.alatpay_service import ALATPayService
from services.order_service import OrderService
from services.product_service import ProductService
from datetime import datetime, timedelta, timezone


logger = logging.getLogger(__name__)

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
            await self.db.refresh(db_payment)
            return db_payment
        except IntegrityError as e:
            await self.db.rollback()
            result = await self.db.execute(select(Payment).where(Payment.order_id == order_id))
            return result.scalars().first()
            

    async def generate_payment_virtual_account(self, payment_id: int, customer_whatsapp_id: str):
        result = await self.db.execute(select(Payment).where(Payment.id == payment_id))
        db_payment = result.scalars().first()
        if not db_payment:
            raise ValueError("Payment not found")

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
            self.db.rollback()
            pass 
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
