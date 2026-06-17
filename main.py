import os
from fastapi import FastAPI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import router after environment variables are loaded
from routes.ai import router as ai_router

app = FastAPI(
    title="WhatsApp Commerce Bot AI Layer",
    description="Python FastAPI service acting as the AI layer for the WhatsApp commerce bot",
    version="0.1.0"
)

# Register routes
app.include_router(ai_router, prefix="/ai")

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
