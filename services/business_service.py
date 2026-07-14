from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models.business import Business
from schemas.business import BusinessCreate, BusinessUpdate


class BusinessService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_business(self, business_data: BusinessCreate, user_id: int):

        try:
            db_business = Business(
                name=business_data.name,
                state=business_data.state,
                city=business_data.city,
                address=business_data.address,
                service=business_data.service,
                phone=business_data.phone,
                user_id=user_id
            )
            self.db.add(db_business)
            await self.db.commit()
            await self.db.refresh(db_business)
            return db_business
        except Exception:
            await self.db.rollback()
            
            raise

    async def get_business_by_id(self, business_id: str):
        result = await self.db.execute(select(Business).where(Business.id == business_id))
        return result.scalars().first()

    async def get_business_by_business_id(self, business_id: str):
        result = await self.db.execute(select(Business).where(Business.id == business_id))
        return result.scalars().first()

    async def get_business_by_user_id(self, user_id: int):
        result = await self.db.execute(select(Business).where(Business.user_id == user_id))
        return result.scalars().first()

    async def get_all_businesses(self, skip: int = 0, limit: int = 10):
        result = await self.db.execute(select(Business).offset(skip).limit(limit))
        return result.scalars().all()

    async def get_available_businesses(self, skip: int = 0, limit: int = 10):
        result = await self.db.execute(
            select(Business)
            .where(Business.is_active == 1)
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def update_business(self, business_id: str, business_data: BusinessUpdate):
        db_business = await self.get_business_by_id(business_id)
        if db_business:
            update_data = business_data.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(db_business, field, value)
            await self.db.commit()
            await self.db.refresh(db_business)
        return db_business
