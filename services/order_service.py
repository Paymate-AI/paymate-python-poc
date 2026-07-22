from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from models.order import Order, OrderItem
from models.product import Product
from schemas.order import OrderCreate


class OrderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_order(self, order_data: OrderCreate) -> Order:
        total_amount = 0.0
        order_items = []

        for item in order_data.items:
            # product = self.db.query(Product).filter(Product.id == item.product_id).first()
            # if not product:
            #     raise ValueError(f"Product with id {item.product_id} not found")
            # if product.stock_quantity < item.quantity:
            #     raise ValueError(f"Insufficient stock for product {product.name}")

            item_total = item.price * item.quantity
            total_amount += item_total

            order_items.append(OrderItem(
                product_id=item.product_id,
                quantity=item.quantity,
                price=item.price
            ))

        db_order = Order(
            business_id=order_data.business_id,
            customer_whatsapp_id=order_data.customer_whatsapp_id,
            total_amount=total_amount,
            items=order_items
        )

        self.db.add(db_order)
        await self.db.commit()
        await self.db.refresh(db_order)
        return db_order

    async def get_order(self, order_id: int) -> Order | None:
        result = await self.db.execute(select(Order).where(Order.id == order_id).options(selectinload(Order.items)))
        return result.scalars().first()
    
    async def get_orders(self) -> list[Order] | None:
        result = await self.db.execute(select(Order).options(selectinload(Order.items)))
        return result.scalars().all()

    async def update_order_status(self, order_id: int, status: str) -> Order | None:
        db_order = await self.get_order(order_id)
        if not db_order:
            return None

        db_order.status = status
        await self.db.commit()
        await self.db.refresh(db_order)
        return db_order

    async def update_inventory_on_payment(self, order_id: int):
        result = await self.db.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        )
        db_order = result.scalars().first()
        if not db_order:
            return

        for item in db_order.items:
            await self.db.execute(
                update(Product)
                .where(Product.id == item.product_id)
                .values(stock_quantity=Product.stock_quantity - item.quantity)
            )

        await self.db.commit()

    
