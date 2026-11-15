"""POST /api/chat (classic JSON) and POST /api/chat/stream (Server-Sent Events).

Both run the same salesperson agent (app/agent). The stream sends events:
status, token, reset, revise, final, error — see app/agent/runner.py.
"""

import json
from typing import AsyncIterator

from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse

from app.agent.runner import collect, run_turn
from app.core.errors import STATUS_BY_CODE
from app.schemas.chat import ChatEnvelope, ChatRequest

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatEnvelope)
async def chat(request: ChatRequest, response: Response) -> ChatEnvelope:
    envelope = await collect(request.conversation_id, request.message)
    if envelope.error is not None:
        response.status_code = STATUS_BY_CODE.get(envelope.error.code, 500)
    return envelope


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    async def sse() -> AsyncIterator[str]:
        async for ev in run_turn(request.conversation_id, request.message):
            yield f"event: {ev['event']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
