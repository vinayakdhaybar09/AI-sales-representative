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
    profile: dict[str, Any]                # what we know about the customer, carried across turns
    # produced along the way
    query: QueryUnderstanding
    pending_resolved: bool                 # this message answered a pending clarification
    pending_before: dict[str, Any] | None  # the clarification that was open when this turn began
    search_text: str                       # text used for retrieval (original + answer when resuming)
    sufficient: bool
    missing_field: str | None
    specialist_result: SpecialistOutput
    composer_attempts: int                 # 1 = first composition, 2 = the single retry
    validation_issues: list[str]           # critical issues from the last validation
    valid: bool                            # the response may be sent as it is
    # final result (built by out_of_scope / clarification / composer)
    response: ChatResponseBody
