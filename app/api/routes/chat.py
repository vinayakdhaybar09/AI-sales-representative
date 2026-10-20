from fastapi import APIRouter, Response

from app.core.errors import STATUS_BY_CODE
from app.schemas.chat import ChatEnvelope, ChatRequest
from app.services.chat_service import handle_chat


router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatEnvelope)
async def chat(request: ChatRequest, response: Response) -> ChatEnvelope:
    envelope = await handle_chat(request)
    if envelope.error is not None:
        response.status_code = STATUS_BY_CODE.get(envelope.error.code, 500)
    return envelope
