"""Query submission specialist: decides to show the in-chat query form and pre-fills it.

Like every specialist it returns data only ({form_id, prefill}); the form itself
is attached by app/response/forms.py. It never writes to the database: the
query is stored only when the customer presses Submit (POST /api/queries).
"""

import re

from app.response.forms import SUPPORT_QUERY
from app.schemas.query import QueryUnderstanding
from app.schemas.specialist import SpecialistOutput

MAX_PREFILL_CHARS = 1000

# First match wins, so the more specific issues come first.
_CATEGORY_WORDS = [
    ("wrong_item", ("wrong item", "wrong product", "incorrect", "different product", "not what i ordered", "sent me a different")),
    ("missing_item", ("missing", "not in the box", "not included", "short of")),
    ("defective", ("defective", "damaged", "broken", "faulty", "not working", "doesn't work", "does not work", "stopped working", "leak", "cracked", "dead on arrival")),
    ("payment", ("payment", "charged", "deducted", "double charge", "debited")),
    ("cancellation", ("cancel",)),
    ("return_refund", ("refund", "money back", "return", "exchange", "replace")),
    ("delivery", ("delay", "not delivered", "not received", "hasn't arrived", "has not arrived", "late", "tracking", "stuck")),
]
_ORDER_ID = re.compile(r"#\s?[A-Za-z]*\d{3,}")


def guess_category(text: str) -> str:
    low = text.lower()
    for category, words in _CATEGORY_WORDS:
        if any(w in low for w in words):
            return category
    return ""


async def run(query: QueryUnderstanding, message: str) -> SpecialistOutput:
    text = (message or "").strip()
    prefill = {
        "category": guess_category(f"{text} {query.resolved_request}"),
        "description": text[:MAX_PREFILL_CHARS],
        "product": query.entities.products[0] if query.entities.products else "",
        "order_id": (_ORDER_ID.search(text).group(0).replace(" ", "") if _ORDER_ID.search(text) else ""),
    }
    return SpecialistOutput(
        specialist="query_submission",
        status="success",
        data={"form_id": SUPPORT_QUERY, "prefill": {k: v for k, v in prefill.items() if v}},
    )
