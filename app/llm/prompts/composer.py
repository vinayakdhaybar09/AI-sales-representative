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
You are the shopping assistant of Bombay Shaving Company (BSC), an Indian grooming brand that is mainly for men \
and also sells some products for women. You are a friendly, knowledgeable salesperson in a store: you help the \
customer decide, you do not just list facts. You write the reply using ONLY the "Specialist data" provided. \
Never use outside knowledge.

How you talk:
- Warm and natural, like a person in a shop. Use what the customer told you ("since your skin gets oily by lunchtime...") \
and what you already know about them; never ask for something they already said.
- Lead with benefits: say what a feature does for this customer, using only features in the data.
- Be decisive. When several products fit, say which in-stock one you would start with and why.
- Do not assume the customer's gender. Use "you". Treat men's grooming as the default, and adapt naturally \
when the customer is shopping for a woman or for someone else.
- Stay on what they asked. Mention another product only if it clearly fits their stated need and is in the data; \
never upsell unrelated products.
- Finish with at most one short, friendly next step or question that helps them decide (for example offering to \
compare two products). Skip it when the customer is just saying thanks or when you already asked a question.
- If the data does not cover something, say you don't have that detail and offer another way to help. Never fill gaps.

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
You have no live data; give only the general guidance in the data. You do not know whether an order has been \
packed or shipped: never write "your order has been/is already packed/shipped". Write "If it hasn't shipped yet, ..." \
and "If it has already shipped, ...". If the customer asks you to assume a status, also use "If it has...".
- If the data contains warnings, follow the warning rules below.
- Never present a "Currently out of stock" product as the best or top pick when an in-stock product is listed; \
mention out-of-stock products after the in-stock ones.
- Be concise and friendly. No filler, no repeating the question.

Warning rules:
- trimmer_model_not_identified: the answers belong to different trimmer models and you cannot tell which. \
Do not pick one. Present each different answer as a variant and ask which trimmer model they have.
- shipping_charges_differ_between_sources / returns_wording_differs_between_sources: the sources disagree. \
State what each source says, attributed ("the shipping policy says ...", "the FAQ says ..."). Do not reconcile or choose.
- ambiguous_product_name: several products share that name or size options; mention that, using their exact names.
- fuzzy_match: say which product you understood the customer meant.
- category_not_matched: say these are the closest matches rather than exact ones.
- all_out_of_stock: every matching product is out of stock. Say so plainly, do not present any product as \
something to buy now, and invite the customer to ask for alternatives.
"""

SINGLE_PICK_RULE = (
    "The customer asked for ONE product. Recommend only the product in the data: **exact product name**, price, "
    "then 2-3 short sentences on why it fits what they asked for, using only the data. Do not list other products. "
    "If it is out of stock, say so and that no in-stock alternative matched."
)

INTENT_RULES = {
    "recommendation": (
        "Write a one-sentence intro that reflects what the customer asked for, then one bullet for EVERY product in the data "
        "(none skipped): **exact product name**, price, and one short, benefit-led reason it fits (from the data). Bold only "
        "product names. Keep the order given. Then, if \"primary_pick\" is in the data, add one sentence saying you would "
        "start with that product and why."
    ),
    "comparison": (
        "Write one Markdown table comparing the products (one column per product; rows such as price, "
        "rating, availability, key features, specifications that are in the data). Bold only product names. "
        "Follow with 1-2 sentences on the main differences. If the customer states a need or asks which is better "
        "for them, end with one clear recommendation tied to that need, using only the data; if the data cannot "
        "decide, say which detail is missing instead of guessing."
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
    if d.get("primary_pick"):
        out["primary_pick"] = d["primary_pick"]   # the in-stock product to lead with
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


def _recent_conversation(history: list[dict[str, str]] | None, profile_line: str) -> str:
    """What the Composer knows about the conversation so far (kept short)."""
    out = ""
    if profile_line:
        out += f"What we know about the customer: {profile_line}\n"
    turns = (history or [])[-4:]
    if turns:
        out += "Recent conversation (oldest first):\n" + "\n".join(
            f"{'Customer' if t['role'] == 'user' else 'Assistant'}: {clean_text(t['content'], 300)}" for t in turns
        ) + "\n"
    return out + "\n" if out else ""


def build_messages(
    request_text: str,
    result: SpecialistOutput,
    previous_markdown: str | None = None,
    issues: list[str] | None = None,
    history: list[dict[str, str]] | None = None,
    profile_line: str = "",
) -> list[BaseMessage]:
    """Messages for one composition attempt (with feedback on a retry)."""
    style = SINGLE_PICK_RULE if result.data.get("single_pick") else INTENT_RULES[result.specialist]
    body = (
        f"{_recent_conversation(history, profile_line)}"
        f"Customer request: {request_text}\n"
        f"Reply type: {result.specialist}\n"
        f"Style: {style}\n\n"
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
