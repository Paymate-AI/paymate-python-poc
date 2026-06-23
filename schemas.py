from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class Message(BaseModel):
    role: str  # 'user' or 'assistant'
    content: str

class ChatRequest(BaseModel):
    customerId: str
    message: str
    history: List[Message] = Field(default_factory=list)

class ChatResponse(BaseModel):
    reply: str
    action: Optional[Dict[str, Any]] = None


class WhatsAppMessage(BaseModel):
    from_number: str
    message_body: str
    business_id: str