from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class UserBase(BaseModel):
    business_id: str
    name: str
    location: str
    service: str
    business_name: str


class UserCreate(UserBase):
    pass


class UserResponse(UserBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
