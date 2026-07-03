from sqlalchemy.orm import Session
from models.business import Business
from schemas.business import BusinessCreate, BusinessUpdate


class BusinessService:
    def __init__(self, db: Session):
        self.db = db

    def create_business(self, business_data: BusinessCreate, user_id: int):

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
            self.db.commit()
            self.db.refresh(db_business)
            return db_business
        except Exception:
            self.db.rollback()
            
            raise

    def get_business_by_id(self, business_id: str):
        return self.db.query(Business).filter(Business.id == business_id).first()

    def get_business_by_business_id(self, business_id: str):
        return self.db.query(Business).filter(Business.id == business_id).first()

    def get_business_by_user_id(self, user_id: int):
        return self.db.query(Business).filter(Business.user_id == user_id).first()

    def get_all_businesses(self, skip: int = 0, limit: int = 10):
        return self.db.query(Business).offset(skip).limit(limit).all()

    def get_available_businesses(self, skip: int = 0, limit: int = 10):
        return self.db.query(Business).filter(Business.is_active == 1).offset(skip).limit(limit).all()

    def update_business(self, business_id: str, business_data: BusinessUpdate):
        db_business = self.get_business_by_id(business_id)
        if db_business:
            update_data = business_data.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(db_business, field, value)
            self.db.commit()
            self.db.refresh(db_business)
        return db_business
