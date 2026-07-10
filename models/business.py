from uuidv7 import uuid7
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database.config import Base


def generate_uuid7():
    return str(uuid7())


class Business(Base):
    __tablename__ = "businesses"

    id = Column(String(40), primary_key=True, index=True, default=generate_uuid7)
    name = Column(String, nullable=False, unique=True)
    state = Column(String, nullable=False)
    city = Column(String, nullable=False)
    address = Column(String, nullable=False)
    service = Column(String, nullable=False)
    phone = Column(String(11), nullable=True)
    is_active = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Foreign key to User
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)

    # Relationships
    user = relationship("User", back_populates="business")
    products = relationship("Product", back_populates="business")