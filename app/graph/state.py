"""app/graph/state.py — the state that flows through the LangGraph workflow.

Each node returns only the keys it changes; LangGraph merges them in.
"""

from typing import TypedDict

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
    # produced along the way
    query: QueryUnderstanding
    sufficient: bool
    missing_field: str | None
    specialist_result: SpecialistOutput
    # final result (built by out_of_scope / clarification / composer)
    response: ChatResponseBody
