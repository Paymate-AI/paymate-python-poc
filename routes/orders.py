from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated
from schemas.order import OrderCreate, OrderResponse
from services.order_service import OrderService
from dependencies import get_order_service

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post(
    "",
    response_model=OrderResponse,
    status_code=201,
    summary="Create a new order",
    description="Create a new order with items, checking product stock before creating"
)
async def create_order(
    order: OrderCreate,
    order_service: Annotated[OrderService, Depends(get_order_service)]
):
    try:
        return order_service.create_order(order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Get an order by ID",
    description="Get a single order's information by its ID"
)
async def get_order(
    order_id: int,
    order_service: Annotated[OrderService, Depends(get_order_service)]
):
    order = order_service.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
