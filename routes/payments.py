import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated
from sqlalchemy.orm import Session
from database.config import get_db
from schemas.payment import PaymentResponse
from services.payment_service import PaymentService
from services.order_service import OrderService
from services.alatpay_service import BadRequestError
from dependencies import get_payment_service, get_order_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post(
    "/order/{order_id}",
    # response_model=PaymentResponse,
    status_code=201,
    summary="Create payment and generate virtual account",
    description="Create a new payment for an order and generate a virtual account via ALATPay"
)
async def create_payment(
    order_id: int,
    payment_service: Annotated[PaymentService, Depends(get_payment_service)],
    order_service: Annotated[OrderService, Depends(get_order_service)]
):
    try:
        order = order_service.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        payment = payment_service.create_payment(order_id, order.total_amount)

    
        payment = await payment_service.generate_payment_virtual_account(
            payment.id,
            order.customer_whatsapp_id
        )
    except BadRequestError as e:

        logger.error(f"Bad request: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid request to generate virtual account: {e}")
    except Exception as e:
        logger.error("An unexpected error occurred", exc_info=True)
        raise HTTPException(status_code=500, detail="An Unexpected error occured")

    return payment


@router.post(
    "/verify/{reference}",
    response_model=PaymentResponse,
    summary="Verify a payment",
    description="Verify payment status via ALATPay using the payment reference"
)
async def verify_payment(
    reference: str,
    payment_service: Annotated[PaymentService, Depends(get_payment_service)]
):
    payment = await payment_service.verify_and_update_payment(reference)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


@router.get(
    "/reference/{reference}",
    response_model=PaymentResponse,
    summary="Get a payment by reference",
    description="Get payment information using the payment reference"
)
async def get_payment(
    reference: str,
    payment_service: Annotated[PaymentService, Depends(get_payment_service)]
):
    payment = payment_service.get_payment_by_reference(reference)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


async def reconcile_payments_task(db: Session):
    """Background task to periodically reconcile pending payments"""
    payment_service = PaymentService(db)
    while True:
        pending_payments = payment_service.get_pending_payments()
        for payment in pending_payments:
            try:
                await payment_service.verify_and_update_payment(payment.reference)
            except ValueError as e:
                logger.error(f"Failed to verify payment: {payment.reference} - {e}")
                continue
            except Exception as e:
                logger.error(f"Failed to verify payment: {payment.reference} - {e}")
                continue
        await asyncio.sleep(100)  # Check every 5 minutes
