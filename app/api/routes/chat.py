from fastapi import APIRouter
from app.schemas.chat import ChatEnvelope, ChatRequest
from app.services.chat_service import handle_chat


router = APIRouter(prefix="/api", tags=["chat"])

@router.post("/chat", response_model=ChatEnvelope)
async def chat(request: ChatRequest) -> ChatEnvelope:
    return await handle_chat(request)