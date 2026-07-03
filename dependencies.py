from typing import Annotated
from fastapi import Depends
from sqlalchemy.orm import Session
from database.config import get_db
from services.user_service import UserService
from services.product_service import ProductService
from services.order_service import OrderService
from services.payment_service import PaymentService
from services.business_service import BusinessService


def get_user_service(db: Annotated[Session, Depends(get_db)]) -> UserService:
    return UserService(db)


def get_business_service(db: Annotated[Session, Depends(get_db)]) -> BusinessService:
    return BusinessService(db)


def get_product_service(db: Annotated[Session, Depends(get_db)]) -> ProductService:
    return ProductService(db)


def get_order_service(db: Annotated[Session, Depends(get_db)]) -> OrderService:
    return OrderService(db)


def get_payment_service(db: Annotated[Session, Depends(get_db)]) -> PaymentService:
    return PaymentService(db)
