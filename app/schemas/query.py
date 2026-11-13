"""app/schemas/query.py — Query Understanding output (see docs/CONTRACTS.md).

The LLM only *extracts*; it never answers or judges sufficiency. All fields
are optional so an empty `{}` for entities/filters/context stays valid.
"""

from typing import Literal

from typing import Any

from pydantic import BaseModel, Field, model_validator

Intent = Literal[
    "recommendation", "product_finalization", "comparison", "knowledge", "support", "query_submission", "conversation"
]
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
    # Only for intent product_finalization (docs/CONTRACTS.md):
    result_limit: int | None = Field(
        default=None, description="How many products the customer wants to end up with (1-3)."
    )
    priority: Literal["lowest_price", "highest_rated"] | None = Field(
        default=None, description="What matters most, only if the customer says so (cheapest / best rated)."
    )


class Context(BaseModel):
    previously_mentioned_product_ids: list[str] = Field(default_factory=list)
    answers_pending_clarification: bool = Field(
        default=False,
        description="True only if the message answers the question the assistant just asked.",
    )


class QueryUnderstanding(BaseModel):
    """Structured reading of one user message."""

    intent: Intent = Field(
        description="recommendation=wants product suggestions; comparison=compare products; "
        "knowledge=grooming/usage/how-to information; support=orders, shipping, returns, policies, contact; "
        "query_submission=wants to report a problem or raise a query/complaint with the support team."
    )
    scope: Scope = Field(description="out_of_scope if the message is unrelated to Bombay Shaving Company.")
    entities: Entities = Field(default_factory=Entities)
    filters: Filters = Field(default_factory=Filters)
    context: Context = Field(default_factory=Context)
    resolved_request: str = Field(
        default="",
        description="The customer's message rewritten as one standalone sentence: 'this issue', 'the first two', "
        "'it' replaced by what they refer to. Nothing the customer did not ask for.",
    )
    requirements: list[str] = Field(
        default_factory=list,
        description="Up to 6 short phrases a good answer must satisfy (the concern, requested material or quality, "
        "budget, which products to compare, how many to pick), including ones carried over from earlier turns.",
    )

    @model_validator(mode="before")
    @classmethod
    def _out_of_scope_is_a_scope(cls, data: Any) -> Any:
        """Small models sometimes answer intent='out_of_scope'. It is a scope value
        (docs/CONTRACTS.md): move it there; such messages are handled by the conversation flow."""
        if isinstance(data, dict) and data.get("intent") == "out_of_scope":
            data = {**data, "intent": "conversation", "scope": "out_of_scope"}
        return data


class Clarification(BaseModel):
    """The single clarifying question the assistant asks."""

    question: str = Field(description="One short question, ending with a question mark.")
