import logging
import uuid
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from models.payment import Payment, VirtualAccount
from services.alatpay_service import ALATPayService
from services.order_service import OrderService
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)

class PaymentService:
    def __init__(self, db: Session):
        self.db = db
        self.order_service = OrderService(db)

    def create_payment(self, order_id: int, amount: float) -> Payment:
        reference = str(uuid.uuid4())
        try:
            db_payment = Payment(
                order_id=order_id,
                amount=amount,
                reference=reference
            )
            self.db.add(db_payment)
            self.db.commit()
            self.db.refresh(db_payment)
            return db_payment
        except IntegrityError as e:
            self.db.rollback()
            return self.db.query(Payment).filter(Payment.order_id == order_id).first()
            

    async def generate_payment_virtual_account(self, payment_id: int, customer_whatsapp_id: str):
        db_payment = self.db.query(Payment).filter(Payment.id == payment_id).first()
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
            self.db.commit()
            self.db.refresh(db_payment)
        except IntegrityError as e:
            self.db.rollback()
            pass 
        return alatpay_response

    async def verify_and_update_payment(self, reference: str) -> Payment | None:
        db_payment = self.db.query(Payment).filter(Payment.reference == reference).first()
        if not db_payment:
            return None

        # Verify with ALATPay
        verification = await ALATPayService.verify_payment(db_payment.transaction_id)

        if verification["status"] == "successful":
            logger.info(f"Payment verification called for reference: {reference}")
            db_payment.status = "successful"
            db_payment.gateway_response = str(verification)

            # Update order status
            self.order_service.update_order_status(db_payment.order_id, "paid")

            # Update inventory
            # TODO: call the ts service to update catalog stock
            # self.order_service.update_inventory_on_payment(db_payment.order_id)

        elif verification["status"] == "failed":
            db_payment.status = "failed"
            db_payment.gateway_response = str(verification)

        self.db.commit()
        self.db.refresh(db_payment)
        return db_payment

    def get_payment_by_reference(self, reference: str) -> Payment | None:
        return self.db.query(Payment).filter(Payment.reference == reference).first()

    def get_pending_payments(self) -> list[Payment]:
        return self.db.query(Payment).filter(Payment.status == "pending").all()
