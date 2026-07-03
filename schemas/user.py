from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from schemas.business import BusinessResponse


class UserCreate(BaseModel):
    name: str
    phone: Optional[str] = None


class UserWithBusinessCreate(BaseModel):
    user: UserCreate
    business: "BusinessCreate"


class UserResponse(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    business: Optional[BusinessResponse] = None

    class Config:
        from_attributes = True


# Import BusinessCreate at the bottom to avoid circular import issues
from schemas.business import BusinessCreate
UserWithBusinessCreate.model_rebuild()

