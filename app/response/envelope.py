"""app/response/envelope.py — wraps a response body (or an error) in the final envelope."""

from app.response.suggested_prompts import FALLBACK_PROMPTS
from app.schemas.chat import ChatEnvelope, ChatResponseBody, ErrorInfo

FALLBACK_MARKDOWN = (
    "I’m unable to verify the exact details right now. "
    "Please try again or ask about a specific product or category."
)


def fallback_body() -> ChatResponseBody:
    """The `fallback` response from docs/CONTRACTS.md."""
    return ChatResponseBody(
        type="fallback",
        markdown=FALLBACK_MARKDOWN,
        product_tray=[],
        suggested_prompts=list(FALLBACK_PROMPTS),
    )


def success_envelope(conversation_id: str, body: ChatResponseBody) -> ChatEnvelope:
    return ChatEnvelope(success=True, conversation_id=conversation_id, response=body, error=None)


def error_envelope(conversation_id: str, code: str, message: str) -> ChatEnvelope:
    return ChatEnvelope(
        success=False,
        conversation_id=conversation_id,
        response=None,
        error=ErrorInfo(code=code, message=message),
    )
