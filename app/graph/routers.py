"""app/graph/routers.py — routing decisions in plain Python (never in prompts)."""

from app.graph.state import ChatState


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
    """Valid -> done. Invalid -> one more composition, then the fallback."""
    if state["valid"]:
        return "finalize"
    if state.get("composer_attempts", 1) < MAX_COMPOSER_ATTEMPTS:
        return "composer"
    return "fallback"
