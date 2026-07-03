from sqlalchemy.orm import Session
from models.order import Order, OrderItem
from models.product import Product
from schemas.order import OrderCreate


class OrderService:
    def __init__(self, db: Session):
        self.db = db

    def create_order(self, order_data: OrderCreate) -> Order:
        total_amount = 0.0
        order_items = []

        for item in order_data.items:
            product = self.db.query(Product).filter(Product.id == item.product_id).first()
            if not product:
                raise ValueError(f"Product with id {item.product_id} not found")
            if product.stock_quantity < item.quantity:
                raise ValueError(f"Insufficient stock for product {product.name}")

            item_total = product.price * item.quantity
            total_amount += item_total

            order_items.append(OrderItem(
                product_id=item.product_id,
                quantity=item.quantity,
                price=product.price
            ))

        db_order = Order(
            business_id=order_data.business_id,
            customer_name=order_data.customer_name,
            total_amount=total_amount,
            items=order_items
        )

        self.db.add(db_order)
        self.db.commit()
        self.db.refresh(db_order)
        return db_order

    def get_order(self, order_id: int) -> Order | None:
        return self.db.query(Order).filter(Order.id == order_id).first()
    
    def get_orders(self) -> list[Order] | None:
        return self.db.query(Order).all()

    def update_order_status(self, order_id: int, status: str) -> Order | None:
        db_order = self.get_order(order_id)
        if not db_order:
            return None

        db_order.status = status
        self.db.commit()
        self.db.refresh(db_order)
        return db_order

    def update_inventory_on_payment(self, order_id: int):
        db_order = self.get_order(order_id)
        if not db_order:
            return

        for item in db_order.items:
            self.db.query(Product).filter(Product.id == item.product_id).update(
                {"stock_quantity": Product.stock_quantity - item.quantity}
            )

        self.db.commit()

    
