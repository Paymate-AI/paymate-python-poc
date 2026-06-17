import os
from fastapi import APIRouter, Header, HTTPException, status
from models import ChatRequest, ChatResponse
from services import gemini

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    x_internal_secret: str = Header(None, alias="X-Internal-Secret")
):
    expected_secret = os.getenv("INTERNAL_SECRET")

    if not expected_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="INTERNAL_SECRET is not configured on the server."
        )

    if not x_internal_secret or x_internal_secret != expected_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )

    try:
        reply = gemini.chat(message=request.message, history=request.history)
        return ChatResponse(reply=reply, action=None)
    except Exception:
        return ChatResponse(reply=f"Mock AI response to: {request.message}", action=None)
