from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from models.user import User
from schemas.user import UserCreate, UserWithBusinessCreate
from services.business_service import BusinessService
from schemas.business import BusinessCreate


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.business_service = BusinessService(db)

    async def create_user_with_business(self, data: UserWithBusinessCreate):
        try:
            db_user = User(
                **data.user.model_dump()
            )
            self.db.add(db_user)
            await self.db.commit()
            await self.db.refresh(db_user)
            
            # Now create the business for this user
            await self.business_service.create_business(data.business, db_user.id)
            
            await self.db.refresh(db_user)
            return db_user
        except IntegrityError as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Business with this name already exists."
            )

    async def create_user(self, user_data: UserCreate) -> User:
        try:
            db_user = User(
                **user_data.model_dump()
            )
            self.db.add(db_user)
            await self.db.commit()
            await self.db.refresh(db_user)
            return db_user
        except IntegrityError as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="User Already Exists."
            )

    async def get_user_by_id(self, user_id: int) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalars().first()

    async def get_all_users(self, skip: int = 0, limit: int = 100) -> list[User]:
        result = await self.db.execute(select(User).offset(skip).limit(limit))
        return result.scalars().all()

