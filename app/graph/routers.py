"""app/graph/routers.py — routing decisions in plain Python (never in prompts)."""

from app.core.config import get_settings
from app.graph.state import ChatState
from app.response.review import should_review


def after_query_understanding(state: ChatState) -> str:
    """Out-of-scope messages skip everything and get a polite decline."""
    if state["query"].scope == "out_of_scope":
        return "out_of_scope"
    return "sufficiency"


def after_sufficiency(state: ChatState) -> str:
    """Insufficient -> one clarification; otherwise the specialist for the intent."""
    if not state["sufficient"]:
        return "clarification"
    return f"specialist_{state['query'].intent}"


MAX_COMPOSER_ATTEMPTS = 2   # first try + exactly one retry


def after_composer(state: ChatState) -> str:
    """Fixed replies (empty result, fallback) skip validation; LLM replies are validated."""
    return "finalize" if state.get("valid") else "validator"


def after_validator(state: ChatState) -> str:
    """Valid -> the reviewer (once, real answers only) or done. Invalid -> one more composition, then the fallback."""
    if state["valid"]:
        reviewable = (
            get_settings().reviewer_enabled
            and not state.get("reviewed")
            and should_review(state["specialist_result"])
        )
        return "reviewer" if reviewable else "finalize"
    if state.get("composer_attempts", 1) < MAX_COMPOSER_ATTEMPTS:
        return "composer"
    return "fallback"


def after_reviewer(state: ChatState) -> str:
    """Fulfilled (or reviewer unavailable) -> done. Otherwise the single revision.

    The reviewer runs once, on the first composition. The revision then goes
    through the deterministic validator only, so it can never loop.
    """
    if state.get("valid") or state.get("composer_attempts", 1) >= MAX_COMPOSER_ATTEMPTS:
        return "finalize"
    return "composer"
