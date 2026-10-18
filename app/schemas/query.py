"""app/schemas/query.py — Query Understanding output (see docs/CONTRACTS.md).

The LLM only *extracts*; it never answers or judges sufficiency. All fields
are optional so an empty `{}` for entities/filters/context stays valid.
"""

from typing import Literal

from typing import Any

from pydantic import BaseModel, Field, model_validator

Intent = Literal["recommendation", "comparison", "knowledge", "support"]
Scope = Literal["in_scope", "out_of_scope"]


class Entities(BaseModel):
    products: list[str] = Field(
        default_factory=list,
        description="Product names exactly as the user wrote them (or resolved from the conversation).",
    )
    category: str | None = Field(
        default=None, description="Product category the user means, e.g. 'trimmer', 'razor', 'beard oil'."
    )
    use_case: list[str] = Field(
        default_factory=list, description="What the user wants it for, e.g. 'beard_grooming', 'body_grooming'."
    )
    body_area: list[str] = Field(default_factory=list, description="e.g. 'face', 'beard', 'scalp', 'body'.")
    attributes: list[str] = Field(
        default_factory=list,
        description="Other subject words: a knowledge topic ('beard growth'), a support topic ('refund'), a quality ('lightweight').",
    )


class Filters(BaseModel):
    budget_max: float | None = None
    budget_min: float | None = None
    skin_type: list[str] = Field(default_factory=list)
    hair_type: list[str] = Field(default_factory=list)
    gender: str | None = None
    required_features: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)


class Context(BaseModel):
    previously_mentioned_product_ids: list[str] = Field(default_factory=list)


class QueryUnderstanding(BaseModel):
    """Structured reading of one user message."""

    intent: Intent = Field(
        description="recommendation=wants product suggestions; comparison=compare products; "
        "knowledge=grooming/usage/how-to information; support=orders, shipping, returns, policies, contact."
    )
    scope: Scope = Field(description="out_of_scope if the message is unrelated to Bombay Shaving Company.")
    entities: Entities = Field(default_factory=Entities)
    filters: Filters = Field(default_factory=Filters)
    context: Context = Field(default_factory=Context)

    @model_validator(mode="before")
    @classmethod
    def _out_of_scope_is_a_scope(cls, data: Any) -> Any:
        """Small models sometimes answer intent='out_of_scope'. It is a scope value
        (docs/CONTRACTS.md), so move it there and keep a neutral intent."""
        if isinstance(data, dict) and data.get("intent") == "out_of_scope":
            data = {**data, "intent": "knowledge", "scope": "out_of_scope"}
        return data
