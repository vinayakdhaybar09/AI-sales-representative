"""POST /api/events — the frontend reports clicks, add-to-cart and chip taps for analytics."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.agent.sessions import log_event
from app.db.connection import get_pool

router = APIRouter(prefix="/api", tags=["events"])


class EventIn(BaseModel):
    conversation_id: str = Field(..., max_length=100)
    event_type: Literal["product_click", "add_to_cart", "chip_click", "checkout", "bundle_add_all", "feedback"]
    product_id: str | None = Field(None, max_length=40)
    meta: dict = Field(default_factory=dict)


@router.post("/events", status_code=202)
async def create_event(event: EventIn) -> dict:
    try:
        async with get_pool().connection() as conn:
            await log_event(conn, event.conversation_id, event.event_type, event.product_id, event.meta)
    except Exception:
        pass  # analytics must never break the chat
    return {"ok": True}
