"""app/response/review.py — pure helpers around the reviewer's verdict.

The reviewer (an LLM) only *suggests*. Python decides what to do with it: an
id is dropped only if it really is in the specialist output, and only for
specialists whose products are a free-standing list.
"""

from app.schemas.review import Review
from app.schemas.specialist import SpecialistOutput

REVIEWABLE = ("recommendation", "product_finalization", "comparison", "knowledge", "support")
EXCLUDABLE = ("recommendation", "product_finalization")   # comparison needs all its products


def should_review(result: SpecialistOutput) -> bool:
    """Only real answers are reviewed; fixed replies and errors never are."""
    return result.status == "success" and result.specialist in REVIEWABLE


def clean_exclusions(review: Review, result: SpecialistOutput) -> list[str]:
    """The reviewer's ids that are actually in the result (others are ignored)."""
    if result.specialist not in EXCLUDABLE:
        return []
    known = {str(p["id"]) for p in result.data.get("products", [])}
    return [i for i in dict.fromkeys(review.exclude_item_ids) if i in known]


def apply_exclusions(result: SpecialistOutput, ids: list[str]) -> SpecialistOutput:
    """The same result without the excluded products.

    The tray is built from this, so it stays a subset of the specialist output.
    Ranks are renumbered so the new first product is the top pick. When nothing
    is left, warning `no_suitable_products` tells the Composer to say so.
    """
    if not ids or result.specialist not in EXCLUDABLE:
        return result
    drop = set(ids)
    kept = [dict(p) for p in result.data.get("products", []) if str(p["id"]) not in drop]
    if result.specialist == "product_finalization":
        for position, product in enumerate(kept, start=1):
            product["rank"] = position
    warnings = list(result.warnings)
    if not kept:
        warnings.append("no_suitable_products")
    return result.model_copy(update={
        "data": {**result.data, "products": kept},
        "sources": [s for s in result.sources if str(s.get("id")) not in drop],
        "warnings": warnings,
    })


def issues_to_text(review: Review) -> list[str]:
    """Reviewer issues as feedback lines for the Composer."""
    return [f"Reviewer ({i.kind}): {i.detail.strip()}" for i in review.issues if i.detail.strip()]
