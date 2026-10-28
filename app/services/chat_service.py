import asyncio
import logging

from app.core import turn_stats
from app.core.config import get_settings
from app.core.errors import INTERNAL_ERROR, classify
from app.graph.builder import get_graph
from app.response.envelope import error_envelope, success_envelope
from app.schemas.chat import ChatEnvelope, ChatRequest

logger = logging.getLogger(__name__)


def _log_turn(conversation_id: str, state: dict | None, stats: turn_stats.TurnStats, outcome: str) -> None:
    """One summary line per turn (log only): what ran, how many model calls, how long."""
    query = (state or {}).get("query")
    response = (state or {}).get("response")
    issues = (state or {}).get("validation_issues") or []
    logger.info(
        "Turn summary (conversation_id=%s, outcome=%s, intent=%s, response=%s, composer_attempts=%s, "
        "llm_calls=%d [%s], embed_calls=%d, llm_s=%.1f, total_s=%.1f, validation_issues=%s)",
        conversation_id, outcome,
        getattr(query, "intent", "-"),
        getattr(response, "type", "-"),
        (state or {}).get("composer_attempts", 0),
        len(stats.llm_calls), stats.llm_summary(), stats.embed_calls,
        stats.llm_seconds, stats.total_seconds,
        "; ".join(issues) if issues else "-",
    )


async def run_turn(request: ChatRequest) -> tuple[ChatEnvelope, turn_stats.TurnStats, dict | None]:
    """Run one chat turn. Returns the envelope, the turn's counters and the final graph state."""
    stats = turn_stats.start_turn()
    state: dict | None = None
    try:
        async with asyncio.timeout(get_settings().request_timeout_seconds):
            state = await get_graph().ainvoke(
                {"conversation_id": request.conversation_id, "message": request.message}
            )
        envelope = success_envelope(request.conversation_id, state["response"])
        _log_turn(request.conversation_id, state, stats, "ok")
        return envelope, stats, state
    except Exception as exc:
        err = classify(exc)
        if err.code == INTERNAL_ERROR:
            logger.exception("Chat workflow failed (conversation_id=%s)", request.conversation_id)
        else:
            logger.warning("Chat request failed: %s (conversation_id=%s, cause=%s)",
                           err.code, request.conversation_id, type(exc).__name__)
        _log_turn(request.conversation_id, state, stats, err.code)
        return error_envelope(request.conversation_id, err.code, err.message), stats, state


async def handle_chat(request: ChatRequest) -> ChatEnvelope:
    """Run the LangGraph workflow and wrap its result in the response envelope.

    Any failure is turned into a client-safe error envelope (see app/core/errors.py);
    stack traces go to the log only.
    """
    logger.info(
        "Chat request received (conversation_id=%s, message_length=%d)",
        request.conversation_id,
        len(request.message),
    )
    logger.debug("Message content: %s", request.message)
    envelope, _, _ = await run_turn(request)
    return envelope
