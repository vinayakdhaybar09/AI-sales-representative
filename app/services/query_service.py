"""app/services/query_service.py — stores a query submitted from the in-chat form.

This is a command, not a chat turn: no graph and no LLM. The content is saved as
sent. Afterwards a short note is added to the conversation so the next message
knows a query was raised; that step never fails the submit.
"""

import asyncio
import logging

from app.core.errors import classify
from app.db.connection import get_pool
from app.db.repositories import support_queries
from app.graph import conversation_store
from app.schemas.chat import ErrorInfo
from app.schemas.support_query import QuerySubmitEnvelope, QuerySubmitRequest

logger = logging.getLogger(__name__)

_background: set[asyncio.Task] = set()   # keeps fire-and-forget tasks alive until they finish


async def submit_query(request: QuerySubmitRequest) -> QuerySubmitEnvelope:
    try:
        async with get_pool().connection() as conn:
            ref = await support_queries.insert_query(
                conn,
                request.conversation_id,
                request.idempotency_key,
                request.category,
                request.description,
                request.details,
                [a.model_dump() for a in request.attachments],
            )
    except Exception as exc:
        err = classify(exc)
        logger.exception("Could not store query (conversation_id=%s)", request.conversation_id)
        return QuerySubmitEnvelope(success=False, error=ErrorInfo(code=err.code, message=err.message))

    logger.info("Query stored (ref=%s, conversation_id=%s, category=%s)", ref, request.conversation_id, request.category)
    # Not awaited: the customer already has their reference, the note is only context for the next message.
    task = asyncio.create_task(conversation_store.add_assistant_note(
        request.conversation_id, f"The customer submitted query {ref} ({request.category or 'general'}) through the form."
    ))
    _background.add(task)
    task.add_done_callback(_background.discard)
    return QuerySubmitEnvelope(success=True, ref=ref)
