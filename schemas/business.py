from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class BusinessBase(BaseModel):
    name: str
    state: str
    city: str
    address: str
    service: str
    phone: Optional[str] = None


class BusinessCreate(BusinessBase):
    pass


class BusinessUpdate(BaseModel):
    name: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    service: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[int] = None


class BusinessResponse(BusinessBase):
    id: str
    is_active: int
    user_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
