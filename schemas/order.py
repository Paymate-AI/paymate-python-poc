from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from decimal import Decimal

class OrderItemBase(BaseModel):
    product_id: str
    quantity: int


class OrderItemCreate(OrderItemBase):
    price : float


class OrderItemResponse(OrderItemBase):
    id: int
    price: float

    class Config:
        from_attributes = True


class OrderBase(BaseModel):
    business_id: str
    customer_whatsapp_id: Optional[str] = None


class OrderCreate(OrderBase):
    items: List[OrderItemCreate]


class OrderResponse(OrderBase):
    id: int
    total_amount: float
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    items: List[OrderItemResponse]

    class Config:
        from_attributes = True
