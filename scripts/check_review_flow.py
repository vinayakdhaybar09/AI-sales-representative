"""scripts/check_review_flow.py — prove the reviewer loop in the real graph (offline).

Usage:  python -m scripts.check_review_flow

No LLM, no database. The real graph runs with stand-ins for: session loader,
query understanding, finalize, the recommendation specialist, the Composer's
model call and the reviewer's model call. We check how many times each runs
and what the final response looks like.
"""

import asyncio
import sys
from types import SimpleNamespace

from app.core.config import get_settings
from app.graph import builder
from app.graph.nodes import composer as composer_node
from app.graph.nodes import reviewer as reviewer_node
from app.graph.nodes import validator as validator_node
from app.schemas.query import Entities, QueryUnderstanding
from app.schemas.review import Review, ReviewIssue
from app.schemas.specialist import SpecialistOutput

FAILED = 0
COMB = {
    "id": "c1", "name": "Hair Comb White", "price": 50.0, "original_price": 50.0, "availability": "in_stock",
    "url": "https://shop.example/comb", "image_url": "https://img.example/comb.webp", "rating": 4.6,
    "review_count": 45, "category": "Accessories", "description": "A lightweight comb with fine teeth.", "details": {},
}
GOOD = "We don't have a wooden comb. The closest is the **Hair Comb White** – ₹50, a lightweight comb with fine teeth."
NONE_LEFT = "We don't have a suitable comb for that right now. I can help you with another grooming need if you like."


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"   ({detail})" if detail and not ok else ""))


async def run_flow(*, replies, reviews, specialist_status="success", reviewer_enabled=True):
    """Run the graph once. `replies`: Composer outputs in order. `reviews`: Review objects or Exceptions in order."""
    calls = SimpleNamespace(composer=[], reviewer=0)
    reply_iter, review_iter = iter(replies), iter(reviews)

    async def fake_session(state):
        return {"history": [], "previous_product_ids": []}

    async def fake_qu(state):
        query = QueryUnderstanding(intent="recommendation", scope="in_scope", entities=Entities(category="hair comb"),
                                   resolved_request="Show a wooden hair comb", requirements=["wooden hair comb"])
        return {"query": query, "search_text": state["message"], "pending_resolved": False, "preferences": {}}

    async def fake_specialist(state):
        if specialist_status == "success":
            return {"specialist_result": SpecialistOutput(
                specialist="recommendation", status="success", data={"products": [dict(COMB)]},
                sources=[{"type": "product", "id": "c1", "name": COMB["name"]}])}
        return {"specialist_result": SpecialistOutput(specialist="recommendation", status="empty", warnings=["no_relevant_products"])}

    async def fake_finalize(state):
        return {}

    async def fake_llm(model, messages):
        return SimpleNamespace(content=next(reply_iter))

    async def fake_get_review(*args, **kwargs):
        calls.reviewer += 1
        item = next(review_iter)
        if isinstance(item, Exception):
            raise item
        return item

    real_build = composer_node.build_messages

    def spy_build(request_text, result, previous=None, issues=None, history=None):
        calls.composer.append({"products": [p["name"] for p in result.data.get("products", [])],
                               "warnings": list(result.warnings), "issues": list(issues or [])})
        return real_build(request_text, result, previous, issues, history)

    saved = (builder.session_loader, builder.query_understanding, builder.finalize, dict(builder.SPECIALISTS),
             composer_node.ainvoke_with_retry, composer_node.build_messages, composer_node.get_chat_model,
             reviewer_node.get_review, validator_node._catalog_names, get_settings().reviewer_enabled)
    try:
        builder.session_loader, builder.query_understanding, builder.finalize = fake_session, fake_qu, fake_finalize
        builder.SPECIALISTS["specialist_recommendation"] = fake_specialist
        composer_node.ainvoke_with_retry, composer_node.build_messages = fake_llm, spy_build
        composer_node.get_chat_model = lambda temperature=0: None
        reviewer_node.get_review = fake_get_review
        validator_node._catalog_names = [COMB["name"]]
        get_settings().reviewer_enabled = reviewer_enabled
        builder.get_graph.cache_clear()
        state = await builder.get_graph().ainvoke({"conversation_id": "t", "message": "wooden hair comb?"})
    finally:
        (builder.session_loader, builder.query_understanding, builder.finalize, specs,
         composer_node.ainvoke_with_retry, composer_node.build_messages, composer_node.get_chat_model,
         reviewer_node.get_review, validator_node._catalog_names, get_settings().reviewer_enabled) = saved
        builder.SPECIALISTS.clear()
        builder.SPECIALISTS.update(specs)
        builder.get_graph.cache_clear()
    return state["response"], calls


async def main() -> int:
    print("Review flow (offline, real graph)")

    r, c = await run_flow(replies=[GOOD], reviews=[Review(fulfils=True)])
    check("fulfilled: one composition, one review, reply unchanged, tray kept",
          len(c.composer) == 1 and c.reviewer == 1 and r.markdown == GOOD and len(r.product_tray) == 1)

    r, c = await run_flow(replies=[GOOD, NONE_LEFT], reviews=[
        Review(fulfils=False, issues=[ReviewIssue(kind="irrelevant", detail="Not a wooden comb.")], exclude_item_ids=["c1"])])
    check("irrelevant product: exactly one revision, reviewer not called again", len(c.composer) == 2 and c.reviewer == 1)
    check("revision is composed without the product and told there is none",
          c.composer[1]["products"] == [] and "no_suitable_products" in c.composer[1]["warnings"], str(c.composer[1]))
    check("revision receives the reviewer's feedback", any("Reviewer (irrelevant)" in i for i in c.composer[1]["issues"]))
    check("final reply is the revision and the tray is empty", r.markdown == NONE_LEFT and r.product_tray == [])

    r, c = await run_flow(replies=[GOOD, GOOD + " (rev)"], reviews=[
        Review(fulfils=False, issues=[ReviewIssue(kind="unsupported", detail="Claim not in the evidence.")])])
    check("unsupported claim: revision keeps the same products and the tray",
          len(c.composer) == 2 and c.composer[1]["products"] == [COMB["name"]] and len(r.product_tray) == 1)

    r, c = await run_flow(replies=[GOOD, "It costs ₹9999 only."], reviews=[
        Review(fulfils=False, issues=[ReviewIssue(kind="missing", detail="x")])])
    check("revision that fails the deterministic validator -> fallback (no third attempt)",
          r.type == "fallback" and len(c.composer) == 2 and c.reviewer == 1)

    r, c = await run_flow(replies=[GOOD], reviews=[RuntimeError("model down")])
    check("reviewer error is fail-open: first reply shipped, no revision",
          len(c.composer) == 1 and r.markdown == GOOD and c.reviewer == 1)

    r, c = await run_flow(replies=[GOOD], reviews=[], reviewer_enabled=False)
    check("reviewer disabled in settings: never called", c.reviewer == 0 and r.markdown == GOOD)

    r, c = await run_flow(replies=[], reviews=[], specialist_status="empty")
    check("empty specialist result: fixed reply, composer LLM and reviewer never run",
          c.reviewer == 0 and len(c.composer) == 0 and r.type == "recommendation" and r.product_tray == [])

    print(f"\n{'ALL FLOW CHECKS PASSED' if not FAILED else str(FAILED) + ' FLOW CHECK(S) FAILED'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
