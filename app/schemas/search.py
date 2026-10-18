"""Dev-only search result shape. Not part of the chat contract."""

from typing import Any, Literal

from pydantic import BaseModel

SourceType = Literal["product", "blog", "support"]


class SearchHit(BaseModel):
    source_type: SourceType
    source_id: str
    content: str
    metadata: dict[str, Any]
    score: float  # cosine similarity, 1.0 = identical direction
