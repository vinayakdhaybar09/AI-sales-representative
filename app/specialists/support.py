"""Support specialist: FAQs and policies. No live order data, ever.

It reports what the support data says, attributed to its source, and surfaces
the known data problems (docs/DATA.md) as warnings instead of resolving them.
"""

import logging
import re

import psycopg

from app.db.repositories.embeddings import find_support_contact_rows
from app.retrieval.search import search
from app.schemas.query import QueryUnderstanding
from app.schemas.search import SearchHit
from app.schemas.specialist import SpecialistOutput

logger = logging.getLogger(__name__)

TOP_K = 5
MIN_SCORE = 0.68
VARIANT_POOL = 50   # how many support rows to scan for repeated trimmer questions

_URL = re.compile(r"https?://[^\s)\]>\"']+")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@bombayshavingcompany\.com")
_RUPEES = re.compile(r"₹\s?(\d+)")


def _question(hit: SearchHit) -> str:
    """First line of the content = the FAQ question (or policy topic)."""
    return re.sub(r"\W+", " ", hit.content.split("\n", 1)[0].lower()).strip()


def _is_trimmer_faq(hit: SearchHit) -> bool:
    return "trimmer" in str(hit.metadata.get("category") or "").lower()


def _contact_info(texts: list[str]) -> dict[str, str | None]:
    """Tracking link and care email exactly as written in the support data."""
    tracking = email = None
    for text in texts:
        if tracking is None:
            tracking = next((u.rstrip(".,") for u in _URL.findall(text) if "track" in u.lower()), None)
        if email is None:
            match = _EMAIL.search(text)
            email = match.group(0) if match else None
    return {"tracking_url": tracking, "care_email": email}


def _conflict_warnings(hits: list[SearchHit]) -> list[str]:
    """Flag known contradictions between retrieved items. Never reconcile them."""
    warnings = []
    shipping = [h for h in hits if "shipping" in h.content.lower() and _RUPEES.search(h.content)]
    amounts = {frozenset(_RUPEES.findall(h.content)) for h in shipping}
    if len(shipping) >= 2 and len(amounts) > 1:
        warnings.append("shipping_charges_differ_between_sources")
    kinds = {h.metadata.get("kind") for h in hits if "return" in h.content.lower()}
    if {"faq", "policy"} <= kinds:
        warnings.append("returns_wording_differs_between_sources")
    return warnings


async def run(
    conn: psycopg.AsyncConnection, query: QueryUnderstanding, search_text: str
) -> SpecialistOutput:
    hits = [h for h in await search(conn, search_text, "support", TOP_K) if h.score >= MIN_SCORE]
    warnings: list[str] = []

    # Trimmer FAQs are not tied to a model: the same question has different
    # answers. Return every variant and never pick one.
    if any(_is_trimmer_faq(h) for h in hits):
        questions = {_question(h) for h in hits if _is_trimmer_faq(h)}
        pool = await search(conn, search_text, "support", VARIANT_POOL)
        variants = [h for h in pool if _is_trimmer_faq(h) and _question(h) in questions]
        extra = [h for h in hits if not _is_trimmer_faq(h)]
        hits = variants + extra
        warnings.append("trimmer_model_not_identified")

    warnings += _conflict_warnings(hits)
    items = [
        {
            "source_id": h.source_id,
            "kind": h.metadata.get("kind"),
            "category": h.metadata.get("category") or h.metadata.get("topic"),
            "content": h.content,
            "score": round(h.score, 3),
        }
        for h in hits
    ]
    contact = _contact_info([h.content for h in hits] + await find_support_contact_rows(conn))

    if not items:
        return SpecialistOutput(
            specialist="support", status="empty",
            data={"contact_info": contact, "live_order_data_available": False},
            warnings=["no_relevant_support_items"],
        )
    return SpecialistOutput(
        specialist="support",
        status="success",
        data={"items": items, "contact_info": contact, "live_order_data_available": False},
        sources=[{"type": "support", "id": i["source_id"], "kind": i["kind"], "category": i["category"]}
                 for i in items],
        warnings=warnings,
    )
