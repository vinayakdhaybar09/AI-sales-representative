from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

ResponseType = Literal[
    "recommendation",
    "comparison",
    "knowledge",
    "support",
    "clarification",
    "out_of_scope",
    "fallback",
]

Availability = Literal["in_stock", "out_of_stock"]

class ChatRequest(BaseModel):
    """What the frontend sends to POST /api/chat."""
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str= Field(..., min_length=1, max_length=1000)
    conversation_id: str= Field(...,min_length=1, max_length=100)


class ProductCard(BaseModel):
    """One product card in the product array."""

    product_id: str
    name: str
    price: float
    image_url: str
    product_url: str
    availability: Availability
    # Optional extras straight from the products table (null when not meaningful):
    rating: float | None = None            # null when the product has no reviews
    review_count: int | None = None        # null when the product has no reviews
    original_price: float | None = None    # only set when higher than price (a real discount)

class ChatResponseBody(BaseModel):
    """The 'response' part of the envelope."""

    type: ResponseType
    markdown: str
    product_tray: list[ProductCard] = Field(default_factory=list)
    suggested_prompts: list[str] = Field(default_factory=list)

class ErrorInfo(BaseModel):
    code: str
    message: str

class ChatEnvelope(BaseModel):
    """The final wrapper returned to the frontend. Always this shape."""
    success: bool
    conversation_id: str
    response: ChatResponseBody | None = None
    error: ErrorInfo | None = None
