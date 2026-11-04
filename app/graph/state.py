"""app/graph/state.py — the state that flows through the LangGraph workflow.

Each node returns only the keys it changes; LangGraph merges them in.
"""

from typing import Any, TypedDict

from app.schemas.chat import ChatResponseBody
from app.schemas.query import QueryUnderstanding
from app.schemas.specialist import SpecialistOutput


class ChatState(TypedDict, total=False):
    # input
    conversation_id: str
    message: str
    # loaded from the conversation store
    history: list[dict[str, str]]          # [{"role": "user"|"assistant", "content": ...}]
    previous_product_ids: list[str]        # product IDs shown earlier in this conversation
    pending_clarification: dict[str, Any] | None   # docs/CONTRACTS.md shape
    pool_search_text: str | None           # search text that produced the last recommendation list
    pool_match_scores: dict[str, float]    # product_id -> similarity score of that list
    finalized_product_ids: list[str]       # the latest product_finalization pick
    preferences: dict[str, Any]            # structured memory of what the customer told us
    shown_products: list[dict[str, Any]]   # [{id, name, category, picked}] from the last answer, in the order shown (not stored)
    fallback_reason: str                   # why the fallback is used: unverified | service | specialist_error
    # produced along the way
    query: QueryUnderstanding
    pending_resolved: bool                 # this message answered a pending clarification
    search_text: str                       # text used for retrieval (original + answer when resuming)
    sufficient: bool
    missing_field: str | None
    specialist_result: SpecialistOutput
    composer_attempts: int                 # 1 = first composition, 2 = the single retry
    validation_issues: list[str]           # critical issues from the last validation
    valid: bool                            # the response may be sent as it is
    reviewed: bool                         # the reviewer has already looked at this turn's reply
    excluded_item_ids: list[str]           # products the reviewer wants removed before the revision
    # final result (built by conversation / clarification / composer)
    response: ChatResponseBody
