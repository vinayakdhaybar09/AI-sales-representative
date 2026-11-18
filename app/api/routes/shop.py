"""Shopping helpers for the frontend: a real store cart link, and the customer profile shown as editable chips."""

import logging
from typing import Any

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field

from app.agent import sessions
from app.agent.tools import PROFILE_KEYS, cart_url
from app.core.config import get_settings
from app.db.connection import get_pool
from app.db.repositories.products import get_product_by_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["shop"])

MAX_CART_PRODUCTS = 20


class CartUrlIn(BaseModel):
    # (product_id, quantity): the same id may appear once; the quantity is capped at 10 like the frontend cart.
    items: list[dict[str, Any]] = Field(..., min_length=1, max_length=MAX_CART_PRODUCTS)


@router.post("/cart-url")
async def build_cart_url(body: CartUrlIn) -> dict:
    """A bombayshavingcompany.com cart link (variant ids from the catalog) for the shopper's bag.

    Returns `cart_url: null` when any product has no variant id, so the frontend never shows a broken link.
    """
    wanted: list[tuple[str, int]] = []
    for item in body.items:
        pid = str(item.get("product_id", ""))
        try:
            qty = max(1, min(10, int(item.get("qty", 1))))
        except (TypeError, ValueError):
            qty = 1
        if pid.isdigit() and len(pid) <= 30:
            wanted.append((pid, qty))
    if not wanted:
        return {"success": False, "cart_url": None}

    rows: list[dict] = []
    async with get_pool().connection() as conn:
        for pid, _ in wanted:
            row = await get_product_by_id(conn, pid)
            if row is None:
                return {"success": True, "cart_url": None}
            rows.append(row)

    base = cart_url(rows)
    if base is None:
        return {"success": True, "cart_url": None}
    # cart_url() writes ":1" for every line; swap in the real quantities.
    head, _, tail = base.rpartition("/cart/")
    lines = [f"{line.split(':')[0]}:{qty}" for line, (_, qty) in zip(tail.split(","), wanted)]
    return {"success": True, "cart_url": f"{head}/cart/" + ",".join(lines)}


@router.get("/conversations/{conversation_id}/profile")
async def get_profile(conversation_id: str = Path(min_length=1, max_length=100)) -> dict:
    """What the assistant remembers about this shopper (skin type, budget, ...), for the editable chips."""
    async with get_pool().connection() as conn:
        sess = await sessions.load_session(conn, conversation_id, get_settings().session_ttl_minutes)
    profile = {k: v for k, v in (sess.get("profile") or {}).items() if k in PROFILE_KEYS and v not in (None, "", [])}
    return {"success": True, "profile": profile}


@router.delete("/conversations/{conversation_id}/profile/{key}")
async def forget_profile_key(
    conversation_id: str = Path(min_length=1, max_length=100),
    key: str = Path(min_length=1, max_length=40),
) -> dict:
    """Shopper removed a chip: forget that one preference. Unknown keys are ignored."""
    if key not in PROFILE_KEYS:
        return {"success": False, "profile": {}}
    async with get_pool().connection() as conn:
        sess = await sessions.load_session(conn, conversation_id, get_settings().session_ttl_minutes)
        profile = dict(sess.get("profile") or {})
        if profile.pop(key, None) is not None:
            await sessions.save_session(conn, conversation_id, sess.get("messages") or [], profile, sess.get("shown_ids") or [])
    return {"success": True, "profile": {k: v for k, v in profile.items() if k in PROFILE_KEYS}}
