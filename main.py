import os
import asyncio
import logging
from fastapi import FastAPI
from dotenv import load_dotenv
from contextlib import asynccontextmanager

# Load environment variables from .env file
load_dotenv()
logging.basicConfig(level=logging.INFO)

from database.config import AsyncEngine, Base
from routes.ai import router as ai_router
from routes.users import router as users_router
from routes.products import router as products_router
from routes.orders import router as orders_router
from routes.payments import router as payments_router, reconcile_payments_task
from routes.businesses import router as businesses_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create database tables on startup
    async with AsyncEngine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Start payment reconciliation background task
    # db_gen = get_db()
    # db = next(db_gen)
    reconciliation_task = asyncio.create_task(reconcile_payments_task())

    yield

    # Cleanup on shutdown
    reconciliation_task.cancel()
    try:
        await reconciliation_task
    except asyncio.CancelledError:
        pass
    # db_gen.close()


app = FastAPI(
    title="Paymate Commerce API",
    description="Complete API for Paymate commerce platform including users, products, orders, and payments with ALATPay integration",
    version="1.0.0",
    lifespan=lifespan
)

# Register routes
app.include_router(ai_router)
app.include_router(users_router)
app.include_router(businesses_router)
app.include_router(products_router)
app.include_router(orders_router)
app.include_router(payments_router)


@app.get("/health")
def health_check():
    """
    Health check endpoint returning status ok.
    """
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    # Read port from environment (default to 8080)
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)

