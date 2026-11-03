import asyncio
import logging

from app.core.config import get_settings
from app.graph.state import ChatState
from app.llm.models import get_chat_model
from app.llm.prompts.reviewer import build_messages
from app.llm.retry import ainvoke_with_retry
from app.response.review import clean_exclusions, issues_to_text
from app.schemas.query import QueryUnderstanding
from app.schemas.review import Review
from app.schemas.specialist import SpecialistOutput

logger = logging.getLogger(__name__)


async def get_review(
    resolved_request: str,
    requirements: list[str],
    history: list[dict[str, str]],
    result: SpecialistOutput,
    markdown: str,
) -> Review:
    """One structured LLM call. Raises on failure; the node decides what that means."""
    model = get_chat_model().with_structured_output(Review)
    review = await ainvoke_with_retry(
        model, build_messages(resolved_request, requirements, history, result, markdown)
    )
    if not isinstance(review, Review):
        raise ValueError("Reviewer returned no structured output")
    return review


def _query_parts(query: QueryUnderstanding | None, message: str) -> tuple[str, list[str]]:
    if query is None:
        return message, []
    return query.resolved_request or message, query.requirements


async def reviewer(state: ChatState) -> dict:
    """Check that the reply fulfils the request. Never blocks an answer.

    Fail-open: any error or timeout means "ship what the validator approved".
    When the reviewer finds problems it marks the response invalid with feedback
    lines, and lists unrelated products to drop; the router then sends it back
    to the Composer (once).
    """
    cid = state["conversation_id"]
    result = state["specialist_result"]
    request, requirements = _query_parts(state.get("query"), state["message"])
    try:
        async with asyncio.timeout(get_settings().reviewer_timeout_seconds):
            review = await get_review(
                request, requirements, state.get("history", []), result, state["response"].markdown
            )
    except Exception:
        logger.warning("Reviewer failed; shipping the validated reply (conversation_id=%s)", cid, exc_info=True)
        return {"reviewed": True}

    if review.fulfils:      # the verdict wins over stray suggestions
        logger.info("Review (conversation_id=%s, fulfils=True)", cid)
        return {"reviewed": True}

    exclude = clean_exclusions(review, result)
    issues = issues_to_text(review)
    if exclude and not issues:
        issues = ["Reviewer (irrelevant): some products shown do not address the request."]
    logger.info(
        "Review (conversation_id=%s, fulfils=%s, issues=%s, excluded=%d)",
        cid, review.fulfils, [i.kind for i in review.issues], len(exclude),
    )
    for line in issues:
        logger.debug("Review issue (conversation_id=%s): %s", cid, line)

    if not issues:
        return {"reviewed": True}
    return {"reviewed": True, "valid": False, "validation_issues": issues, "excluded_item_ids": exclude}
