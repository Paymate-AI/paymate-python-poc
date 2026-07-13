import os
import httpx
import logging
from sqlalchemy.orm import Session
from models.product import Product
from schemas.product import ProductCreate, ProductUpdate



TS_SERVICE_URL = os.getenv("TS_SERVICE_URL", "")
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "")
logger = logging.getLogger(__name__)

class ProductService:
    def __init__(self, db: Session):
        self.db = db

    def create_product(self, product_data: ProductCreate) -> Product:
        db_product = Product(**product_data.model_dump())
        self.db.add(db_product)
        self.db.commit()
        self.db.refresh(db_product)
        return db_product

    def get_product(self, product_id: int) -> Product | None:
        return self.db.query(Product).filter(Product.id == product_id).first()

    def get_products_by_business(self, business_id: int, skip: int = 0, limit: int = 100) -> list[Product]:
        return self.db.query(Product).filter(Product.business_id == business_id).offset(skip).limit(limit).all()

    def get_available_products(self, business_id: int, skip: int = 0, limit: int = 100) -> list[Product]:
        return self.db.query(Product).filter(
            Product.business_id == business_id,
            Product.is_active == True,
            Product.stock_quantity > 0
        ).offset(skip).limit(limit).all()

    def get_out_of_stock_products(self, business_id: int, skip: int = 0, limit: int = 100) -> list[Product]:
        return self.db.query(Product).filter(
            Product.business_id == business_id,
            Product.is_active == True,
            Product.stock_quantity == 0
        ).offset(skip).limit(limit).all()

    def update_product(self, product_id: int, product_data: ProductUpdate) -> Product | None:
        db_product = self.get_product(product_id)
        if not db_product:
            return None

        update_data = product_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_product, field, value)

        self.db.commit()
        self.db.refresh(db_product)
        return db_product

    def update_stock(self, product_id: int, quantity: int, action: str) -> Product | None:
      
        url = f"{TS_SERVICE_URL}/internal/catalog-item/update"
        headers = {
            "Authorization": f"Bearer {os.getenv('INTERNAL_SECRET', '')}",
            "Content-Type": "application/json"
        }
        payload = {
            "catagoryId": product_id,
            "quantity": quantity,
            "action": action
        }
        message = "Product Quatity update failed"
        try:
            with httpx.Client() as client_http:
                response = client_http.post(url, json=payload, headers=headers, timeout=10.0)
                if response.status_code != 200:
                    logger.error(
                        "TS inventory update failed for product %s quantity %s: %s",
                        product_id,
                        quantity,
                        response.text,
                    )
                    return (False, message)
                message = "Product Quantity updated successfully"
                return (True, message)
        except httpx.RequestError as e:
            logger.error("TS inventory update request failed for product %s: %s", product_id, str(e))
            return (False, message)

