import uuid
from sqlalchemy.orm import Session
from models.payment import Payment, VirtualAccount
from services.alatpay_service import ALATPayService
from services.order_service import OrderService
from datetime import datetime, timedelta


class PaymentService:
    def __init__(self, db: Session):
        self.db = db
        self.order_service = OrderService(db)

    def create_payment(self, order_id: int, amount: float) -> Payment:
        reference = str(uuid.uuid4())
        db_payment = Payment(
            order_id=order_id,
            amount=amount,
            reference=reference
        )
        self.db.add(db_payment)
        self.db.commit()
        self.db.refresh(db_payment)
        return db_payment

    async def generate_payment_virtual_account(self, payment_id: int, customer_name: str):
        db_payment = self.db.query(Payment).filter(Payment.id == payment_id).first()
        if not db_payment:
            raise ValueError("Payment not found")

        # Call ALATPay to generate virtual account
        alatpay_response = await ALATPayService.generate_virtual_account(
            amount=db_payment.amount,
            reference=db_payment.reference,
            customer_name=customer_name
        )

        # Create virtual account record
        expiry_date = datetime.now() + timedelta(minutes=alatpay_response.get("expiry_minutes", 60))
        db_virtual_account = VirtualAccount(
            payment_id=payment_id,
            account_number=alatpay_response["account_number"],
            account_name=alatpay_response["account_name"],
            bank_name=alatpay_response["bank_name"],
            expiry_date=expiry_date
        )
        self.db.add(db_virtual_account)
        self.db.commit()
        self.db.refresh(db_payment)
        return db_payment

    async def verify_and_update_payment(self, reference: str) -> Payment | None:
        db_payment = self.db.query(Payment).filter(Payment.reference == reference).first()
        if not db_payment:
            return None

        # Verify with ALATPay
        verification = await ALATPayService.verify_payment(reference)

        if verification["status"] == "successful":
            db_payment.status = "successful"
            db_payment.gateway_response = str(verification)

            # Update order status
            self.order_service.update_order_status(db_payment.order_id, "paid")

            # Update inventory
            self.order_service.update_inventory_on_payment(db_payment.order_id)

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
