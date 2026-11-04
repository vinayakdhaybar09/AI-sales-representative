"""scripts/check_fallbacks.py — fallbacks by reason/context and follow-up resolution (offline, no LLM, no DB).

Usage:  python -m scripts.check_fallbacks
"""

import asyncio
import sys
from types import SimpleNamespace

from app.graph import builder
from app.graph.nodes import composer as composer_node
from app.graph.nodes import validator as validator_node
from app.graph.nodes.fallback import build_fallback
from app.response.conversation import problems
from app.response.fallbacks import SERVICE, SPECIALIST_ERROR, UNVERIFIED, fallback_text
from app.schemas.query import Entities, QueryUnderstanding
from app.schemas.specialist import SpecialistOutput
from app.specialists.products import match_shown_products

FAILED = 0
SHOWN = [
    {"id": "1", "name": "Hair Removal Cream, 100g", "category": "Hair removal"},
    {"id": "2", "name": "Hair Removal Spray, 200ml", "category": "Hair removal"},
    {"id": "3", "name": "Sensi Smart 3 Razor", "category": "Razors"},
]


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"   ({detail})" if detail and not ok else ""))


def query(intent, products=None, category=None) -> QueryUnderstanding:
    return QueryUnderstanding(intent=intent, scope="in_scope", entities=Entities(products=products or [], category=category))


def part_templates() -> None:
    print("Fallback text by reason and context")
    two = fallback_text(UNVERIFIED, ["Hair Removal Cream", "Hair Removal Spray"], None, "seed")
    check("two products: names both in the text", "Hair Removal Cream" in two and "Hair Removal Spray" in two)
    one = fallback_text(UNVERIFIED, ["Hair Removal Cream"], None, "seed")
    check("one product: its name in the text", "Hair Removal Cream" in one)
    cat = fallback_text(UNVERIFIED, [], "Face Wash", "seed")
    check("category only: mentions the category, lower-cased", "face wash" in cat and "Face Wash" not in cat)
    none = fallback_text(UNVERIFIED, [], None, "seed")
    check("no context: asks for a product or category", "product or category" in none)
    check("service failure says so and does not blame the question", "try again" in fallback_text(SERVICE, ["A", "B"], None, "x").lower())
    check("lookup failure is its own message", fallback_text(SPECIALIST_ERROR, [], None, "x") != fallback_text(SERVICE, [], None, "x"))
    check("a service failure never names products", "Hair Removal" not in fallback_text(SERVICE, ["Hair Removal Cream"], None, "x"))
    texts = [fallback_text(r, n, c, s) for r in (UNVERIFIED, SERVICE, SPECIALIST_ERROR)
             for n in ([], ["A"], ["A", "B"]) for c in (None, "razor") for s in ("a", "b", "c")]
    check("every template passes the voice guardrails (<=1 '!', no price/link/markup)",
          all(t.count("!") <= 1 and not problems(t) for t in texts), next((t for t in texts if t.count("!") > 1 or problems(t)), ""))
    check("different seeds can give different wording", len({fallback_text(UNVERIFIED, [], None, s) for s in ("a", "b")}) == 2)


def part_context() -> None:
    print("Fallback context from the conversation state")
    st = {"message": "difference between the cream and the spray", "shown_products": SHOWN, "preferences": {"category": "hair removal"}}
    text = build_fallback({**st, "query": query("comparison")}, UNVERIFIED).markdown
    check("comparison with nothing resolved: names the products just shown", "Hair Removal Cream" in text and "Hair Removal Spray" in text)
    text = build_fallback({**st, "query": query("comparison", ["Sensi Smart 3 Razor"])}, UNVERIFIED).markdown
    check("comparison with resolved names: uses those", "Sensi Smart 3 Razor" in text and "Hair Removal" not in text)
    text = build_fallback({**st, "query": query("support")}, UNVERIFIED).markdown
    check("a support question never gets product names", "Hair Removal" not in text and "Razor" not in text)
    text = build_fallback({**st, "query": query("recommendation", category="razor")}, UNVERIFIED).markdown
    check("recommendation: asks about the category from memory", "hair removal" in text)
    r = build_fallback({**st, "query": query("comparison")}, UNVERIFIED)
    check("response keeps the fixed parts of the contract", r.type == "fallback" and r.product_tray == [] and len(r.suggested_prompts) == 2)


def part_matching() -> None:
    print("Resolving follow-ups to the products just shown")
    ids = lambda term: [p["id"] for p in match_shown_products(term, SHOWN)]  # noqa: E731
    check("'the cream' -> the cream", ids("the cream") == ["1"])
    check("'the spray' -> the spray", ids("the spray") == ["2"])
    check("exact name wins", ids("Sensi Smart 3 Razor") == ["3"])
    check("a shared category word is ambiguous (both returned)", ids("hair removal") == ["1", "2"])
    check("unknown words match nothing", ids("wax") == [] and ids("the second one") == [] and ids("") == [])
    check("plural/singular tolerated", ids("razors") == ["3"])


async def part_flow() -> None:
    print("Graph: failures end in a reason-aware fallback")
    saved = (builder.session_loader, builder.query_understanding, builder.finalize, dict(builder.SPECIALISTS),
             composer_node.ainvoke_with_retry, composer_node.get_chat_model, validator_node._catalog_names)

    async def run(composer_error=False, specialist_status="success", reply="It costs ₹9999 only."):
        async def fake_session(state):
            return {"history": [], "shown_products": SHOWN, "preferences": {}}

        async def fake_qu(state):
            return {"query": query("comparison", ["Hair Removal Cream", "Hair Removal Spray"]), "search_text": state["message"],
                    "pending_resolved": False, "preferences": {}}   # two names: sufficiency passes, no clarification

        async def fake_specialist(state):
            product = {"id": "1", "name": "Hair Removal Cream", "price": 99.0, "original_price": 99.0, "availability": "in_stock",
                       "url": "https://shop.example/1", "image_url": "", "category": "x", "details": {}}
            return {"specialist_result": SpecialistOutput(specialist="comparison", status=specialist_status,
                                                          data={"products": [product, dict(product, id="2", name="Hair Removal Spray")]})}

        async def fake_finalize(state):
            return {}

        async def fake_llm(model, messages):
            if composer_error:
                raise RuntimeError("model down")
            return SimpleNamespace(content=reply)

        builder.session_loader, builder.query_understanding, builder.finalize = fake_session, fake_qu, fake_finalize
        builder.SPECIALISTS["specialist_comparison"] = fake_specialist
        composer_node.ainvoke_with_retry, composer_node.get_chat_model = fake_llm, (lambda temperature=0: None)
        validator_node._catalog_names = ["Hair Removal Cream", "Hair Removal Spray"]
        builder.get_graph.cache_clear()
        state = await builder.get_graph().ainvoke({"conversation_id": "t", "message": "difference between the cream and the spray"})
        return state["response"]

    try:
        r = await run()
        check("failed validation twice -> 'unverified' text naming the shown products",
              r.type == "fallback" and "Hair Removal Cream" in r.markdown and "Hair Removal Spray" in r.markdown, r.markdown)
        r = await run(composer_error=True)
        check("model failure -> 'service' text", r.type == "fallback" and "Hair Removal" not in r.markdown and "again" in r.markdown, r.markdown)
        r = await run(specialist_status="error")
        check("specialist failure -> its own text", r.type == "fallback" and ("look that up" in r.markdown or "went wrong" in r.markdown), r.markdown)
    finally:
        (builder.session_loader, builder.query_understanding, builder.finalize, specs,
         composer_node.ainvoke_with_retry, composer_node.get_chat_model, validator_node._catalog_names) = saved
        builder.SPECIALISTS.clear()
        builder.SPECIALISTS.update(specs)
        builder.get_graph.cache_clear()


def main() -> int:
    part_templates()
    part_context()
    part_matching()
    asyncio.run(part_flow())
    print(f"\n{'ALL FALLBACK CHECKS PASSED' if not FAILED else str(FAILED) + ' CHECK(S) FAILED'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
