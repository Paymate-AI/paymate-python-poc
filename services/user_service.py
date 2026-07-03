from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from models.user import User
from schemas.user import UserCreate, UserWithBusinessCreate
from services.business_service import BusinessService
from schemas.business import BusinessCreate


class UserService:
    def __init__(self, db: Session):
        self.db = db
        self.business_service = BusinessService(db)

    def create_user_with_business(self, data: UserWithBusinessCreate):
        try:
            db_user = User(
                **data.user.model_dump()
            )
            self.db.add(db_user)
            self.db.commit()
            self.db.refresh(db_user)
            
            # Now create the business for this user
            self.business_service.create_business(data.business, db_user.id)
            
            self.db.refresh(db_user)
            return db_user
        except IntegrityError as e:
            self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Business with this name already exists."
            )

    def create_user(self, user_data: UserCreate) -> User:
        try:
            db_user = User(
                **user_data.model_dump()
            )
            self.db.add(db_user)
            self.db.commit()
            self.db.refresh(db_user)
            return db_user
        except IntegrityError as e:
            self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="User Already Exists."
            )

    def get_user_by_id(self, user_id: int) -> User | None:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_all_users(self, skip: int = 0, limit: int = 100) -> list[User]:
        return self.db.query(User).offset(skip).limit(limit).all()

