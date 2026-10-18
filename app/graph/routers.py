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
