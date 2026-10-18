"""app/schemas/specialist.py — common specialist output (see docs/CONTRACTS.md)."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class SpecialistOutput(BaseModel):
    specialist: Literal["recommendation", "comparison", "knowledge", "support"]
    status: Literal["success", "empty", "error"]
    data: dict[str, Any] = Field(default_factory=dict)
    sources: list[Any] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
