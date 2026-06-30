from sqlalchemy.orm import Session
from models.product import Product
from schemas.product import ProductCreate, ProductUpdate


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

    def get_products_by_business(self, business_id: str, skip: int = 0, limit: int = 100) -> list[Product]:
        return self.db.query(Product).filter(Product.business_id == business_id).offset(skip).limit(limit).all()

    def get_available_products(self, business_id: str, skip: int = 0, limit: int = 100) -> list[Product]:
        return self.db.query(Product).filter(
            Product.business_id == business_id,
            Product.is_active == True,
            Product.stock_quantity > 0
        ).offset(skip).limit(limit).all()

    def get_out_of_stock_products(self, business_id: str, skip: int = 0, limit: int = 100) -> list[Product]:
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

    def update_stock(self, product_id: int, quantity: int) -> Product | None:
        db_product = self.get_product(product_id)
        if not db_product:
            return None

        db_product.stock_quantity += quantity
        self.db.commit()
        self.db.refresh(db_product)
        return db_product
