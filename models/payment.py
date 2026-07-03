from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database.config import Base


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), unique=False, nullable=False)
    amount = Column(Float, nullable=False)
    reference = Column(String, unique=True, nullable=False)
    status = Column(String, default="pending")  # pending, successful, failed
    gateway_response = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    transaction_id = Column(String, unique=True, nullable=True)
    order = relationship("Order", back_populates="payment")
    virtual_account = relationship("VirtualAccount", back_populates="payment", uselist=False)


class VirtualAccount(Base):
    __tablename__ = "virtual_accounts"

    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), unique=True, nullable=False)
    account_number = Column(String, nullable=False)
    account_name = Column(String, nullable=False)
    bank_name = Column(String, nullable=False)
    expiry_date = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    payment = relationship("Payment", back_populates="virtual_account")
