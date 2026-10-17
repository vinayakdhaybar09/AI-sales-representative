import logging

from app.schemas.chat import (
    ChatEnvelope,
    ChatRequest,
    ChatResponseBody,
    ProductCard,
)

logger = logging.getLogger(__name__)


async def handle_chat(request: ChatRequest) -> ChatEnvelope:
    """Phase 2 STUB. Returns fake data in the real response shape.

    Later phases replace the body of this function with a call to the
    LangGraph workflow. The signature (request in, envelope out) stays.
    """

    logger.info(
        "Chat request received (conversation_id=%s, message_length=%d)",
        request.conversation_id,
        len(request.message),
    )
    logger.debug("Message content: %s", request.message)

    text = request.message.lower()

    if "recommend" in text or "suggest" in text:
        body = ChatResponseBody(
            type="recommendation",
            markdown="**[STUB]** Here are two sample products.",
            product_tray=[
                ProductCard(
                    product_id="stub_001",
                    name="Sample Razor (in stock)",
                    price=499.0,
                    image_url="https://example.com/razor.webp",
                    product_url="https://example.com/products/razor",
                    availability="in_stock",
                ),
                ProductCard(
                    product_id="stub_002",
                    name="Sample Body Wash (out of stock)",
                    price=299.0,
                    image_url="https://example.com/wash.webp",
                    product_url="https://example.com/products/wash",
                    availability="out_of_stock",
                ),
            ],
        )
    else:
        body = ChatResponseBody(
            type="knowledge",
            markdown=f"**[STUB]** You said: {request.message}",
            suggested_prompts=["Suggest a razor for sensitive skin"],
        )

    return ChatEnvelope(
        success=True,
        conversation_id=request.conversation_id,
        response=body,
        error=None,
    )