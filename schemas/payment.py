from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class VirtualAccountResponse(BaseModel):
    id: int
    account_number: str
    account_name: str
    bank_name: str
    expiry_date: Optional[datetime] = None
    # created_at: datetime

    class Config:
        from_attributes = True


class PaymentResponse(BaseModel):
    id: int
    order_id: int
    amount: float
    reference: str
    status: str
    transaction_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    virtual_account: Optional[VirtualAccountResponse] = None

    class Config:
        from_attributes = True
