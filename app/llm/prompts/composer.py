"""Prompt + data serialiser for the Composer.

The Composer writes Markdown from specialist output ONLY. This module decides
what the model gets to see: names, prices, availability, descriptions and
retrieved text, but never product IDs, product URLs or image URLs (those live
in the tray, which Python builds).
"""

import json
import re
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.schemas.specialist import SpecialistOutput

SYSTEM_PROMPT = """\
You are the shopping assistant of Bombay Shaving Company (BSC), an Indian men's grooming brand. \
You write the reply to a customer using ONLY the "Specialist data" provided. Never use outside knowledge.

Hard rules:
- Never invent or change product names, prices, features, policies, URLs or contact details. \
Quote prices as ₹<amount> exactly as given. If something is not in the data, do not mention it.
- Output Markdown only (it is rendered with react-markdown): short paragraphs, bullet lists, tables. No HTML.
- Do NOT write product IDs, product page links or image links. A product card tray with images and links \
is shown separately by the app.
- A product whose availability is "Currently out of stock" must be described with exactly the words \
"Currently out of stock". Never hide or skip out-of-stock products.
- "no ratings yet" means there are no reviews: say so or leave rating out; never write a 0 rating.
- Never state anything about the customer's own order, delivery, refund or payment status. \
You have no live data; give only the general guidance in the data.
- If the data contains warnings, follow the warning rules below.
- Be concise and friendly. No filler, no repeating the question.

Warning rules:
- trimmer_model_not_identified: the answers belong to different trimmer models and you cannot tell which. \
Do not pick one. Present each different answer as a variant and ask which trimmer model they have.
- shipping_charges_differ_between_sources / returns_wording_differs_between_sources: the sources disagree. \
State what each source says, attributed ("the shipping policy says ...", "the FAQ says ..."). Do not reconcile or choose.
- ambiguous_product_name: several products share that name or size options; mention that, using their exact names.
- fuzzy_match: say which product you understood the customer meant.
- category_not_matched: say these are the closest matches rather than exact ones.
"""

INTENT_RULES = {
    "recommendation": (
        "Write a one-sentence intro, then one bullet for EVERY product in the data (none skipped): **exact product name**, price, and one short, "
        "data-based reason it fits. Bold only product names. Keep the order given."
    ),
    "comparison": (
        "Write one Markdown table comparing the products (one column per product; rows such as price, "
        "rating, availability, key features, specifications that are in the data). Bold only product names. "
        "Follow with 1-2 sentences on the main differences. Do not declare a winner unless the data supports it."
    ),
    "knowledge": (
        "Answer the question from the article excerpts in a few short paragraphs or bullets. "
        "If helpful, end with a link to the article using only the URL given for it. "
        "If products are listed, mention them by exact name."
    ),
    "support": (
        "Answer from the support items. If the customer asks about tracking, include the tracking link and the care "
        "email exactly as given in contact_info. Attribute policy statements to their source (FAQ or policy)."
    ),
}

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def clean_text(text: Any, limit: int) -> str:
    """Strip stray HTML/CSS comments and tags, collapse whitespace, cap length."""
    s = _SPACE.sub(" ", _TAG.sub(" ", _COMMENT.sub(" ", str(text or "")))).strip()
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + "…"


def _product_view(p: dict[str, Any], with_specs: bool) -> dict[str, Any]:
    details = p.get("details") or {}
    view: dict[str, Any] = {
        "name": p["name"],
        "category": p.get("category"),
        "price": f"₹{p['price']:g}",
        "availability": "in stock" if p["availability"] == "in_stock" else "Currently out of stock",
        "rating": f"{p['rating']:g}/5 from {p['review_count']} reviews" if p.get("rating") else "no ratings yet",
        "description": clean_text(p.get("description"), 300),
        "features": [clean_text(f, 120) for f in (details.get("features") or [])[:6]],
    }
    if p.get("original_price") and p["original_price"] > p["price"]:
        view["original_price"] = f"₹{p['original_price']:g}"
    if with_specs:
        specs = {k: v for k, v in (details.get("specifications") or {}).items() if k != "options"}
        view["specifications"] = {k: clean_text(v, 80) for k, v in list(specs.items())[:8]}
    return view


def serialise(result: SpecialistOutput) -> str:
    """Specialist output -> compact JSON the Composer may use."""
    d = result.data
    out: dict[str, Any] = {"status": result.status, "warnings": result.warnings}
    with_specs = result.specialist == "comparison"
    if d.get("products"):
        out["products"] = [_product_view(p, with_specs) for p in d["products"]]
    if d.get("chunks"):
        out["articles"] = [
            {"title": c["title"], "heading": c["heading"], "url": c["url"], "excerpt": clean_text(c["content"], 1200)}
            for c in d["chunks"]
        ]
    if d.get("items"):
        out["support_items"] = [
            {"kind": i["kind"], "category": i["category"], "text": clean_text(i["content"], 1500)}
            for i in d["items"]
        ]
        out["contact_info"] = d.get("contact_info")
        out["live_order_data_available"] = False
    return json.dumps(out, ensure_ascii=False, indent=1)


def build_messages(
    request_text: str,
    result: SpecialistOutput,
    previous_markdown: str | None = None,
    issues: list[str] | None = None,
) -> list[BaseMessage]:
    """Messages for one composition attempt (with feedback on a retry)."""
    body = (
        f"Customer request: {request_text}\n"
        f"Reply type: {result.specialist}\n"
        f"Style: {INTENT_RULES[result.specialist]}\n\n"
        f"Specialist data:\n{serialise(result)}"
    )
    if previous_markdown and issues:
        body += (
            "\n\nYour previous reply was rejected by an automatic checker.\n"
            "Problems:\n" + "\n".join(f"- {i}" for i in issues)
            + f"\n\nPrevious reply:\n{previous_markdown}\n\n"
            "Write a corrected reply that fixes every problem and uses only the data above."
        )
    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=body)]
