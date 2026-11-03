"""app/schemas/review.py — the reviewer's structured verdict (see docs/CONTRACTS.md)."""

from typing import Literal

from pydantic import BaseModel, Field

IssueKind = Literal["missing", "unsupported", "irrelevant"]


class ReviewIssue(BaseModel):
    kind: IssueKind = Field(
        description="missing = a requirement is ignored or something asked for is not answered; "
        "unsupported = a claim that is not in the evidence; "
        "irrelevant = an item shown as a solution that does not address the request."
    )
    detail: str = Field(description="One short sentence saying what to fix.")


class Review(BaseModel):
    """Does the reply fulfil the customer's request, judged against the evidence?"""

    fulfils: bool = Field(description="True only when there are no issues.")
    issues: list[ReviewIssue] = Field(default_factory=list)
    exclude_item_ids: list[str] = Field(
        default_factory=list,
        description="Ids (from the item list) of products shown as a fit that do not address the request.",
    )
