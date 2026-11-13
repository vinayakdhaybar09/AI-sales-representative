"""app/schemas/support_query.py — POST /api/queries (the in-chat query form submit).

Only sizes and types are limited (to keep one request from filling the database).
The content is stored as the customer typed it.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.chat import ErrorInfo


class AttachmentMeta(BaseModel):
    """Only the file's description; the file itself never leaves the browser."""

    name: str = Field(..., max_length=200)
    size: int = Field(0, ge=0)
    type: str = Field("", max_length=100)


class QuerySubmitRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    conversation_id: str = Field(..., min_length=1, max_length=100)
    idempotency_key: str = Field(..., min_length=8, max_length=100)
    category: str = Field("", max_length=100)
    description: str = Field(..., min_length=1, max_length=2000)
    details: dict[str, Any] = Field(default_factory=dict)
    attachments: list[AttachmentMeta] = Field(default_factory=list, max_length=10)


class QuerySubmitEnvelope(BaseModel):
    success: bool
    ref: str | None = None
    error: ErrorInfo | None = None
