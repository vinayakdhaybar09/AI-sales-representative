"""scripts/check_composition.py — prove the validator and retry/fallback logic.

Usage:  python -m scripts.check_composition

Part A (offline, no LLM/DB): good and bad responses against fake specialist data;
        every critical rule must trigger, a good response must pass.
Part B (needs DB + Mistral for Query Understanding): the Composer LLM is replaced by a
        stub that always returns a bad answer; the graph must compose exactly twice
        (one retry) and then return the `fallback` response.
"""

import asyncio
import sys
from types import SimpleNamespace

from app.response.tray import build_tray
from app.response.validator import validate
from app.schemas.chat import ChatResponseBody
from app.schemas.specialist import SpecialistOutput

PRODUCTS = [
    {"id": "1", "name": "Alpha Razor", "price": 99.0, "availability": "in_stock",
     "url": "https://shop.example/alpha", "image_url": "https://img.example/alpha.webp", "details": {}},
    {"id": "2", "name": "Beta Foam, 50g", "price": 49.0, "availability": "out_of_stock",
     "url": "https://shop.example/beta", "image_url": "https://img.example/beta.webp", "details": {}},
]
REC = SpecialistOutput(specialist="recommendation", status="success", data={"products": PRODUCTS})
SUP = SpecialistOutput(
    specialist="support", status="success",
    data={"items": [{"content": "Track here https://track.example/x or email care@bombayshavingcompany.com. Fee ₹99."}],
          "contact_info": {"tracking_url": "https://track.example/x", "care_email": "care@bombayshavingcompany.com"}},
)
CATALOG = ["Alpha Razor", "Beta Foam, 50g", "Gamma Trimmer"]


def body(kind, md, tray=None):
    return ChatResponseBody(type=kind, markdown=md, product_tray=tray if tray is not None else [])


def cases():
    tray = build_tray(REC)
    good = "Try **Alpha Razor** at ₹99 or **Beta Foam, 50g** at ₹49 (Currently out of stock)."
    yield "good recommendation", body("recommendation", good, tray), REC, None
    yield "invented price", body("recommendation", good.replace("₹99", "₹149"), tray), REC, "amount"
    yield "invented URL", body("recommendation", good + " See https://fake.example/p", tray), REC, "URL"
    yield "missing out-of-stock wording", body("recommendation", good.replace("(Currently out of stock)", ""), tray), REC, "out-of-stock"
    yield "product not in result", body("recommendation", good + " Also **Gamma Trimmer**.", tray), REC, "not in the specialist result"
    yield "tray price tampered", body("recommendation", good, [tray[0].model_copy(update={"price": 1.0}), tray[1]]), REC, "differs"
    yield "tray has extra product", body("recommendation", good, tray + [tray[0]]), REC, "tray has"
    yield "tray missing", body("recommendation", good, []), REC, "tray has"
    yield "wrong type", body("knowledge", good, tray), REC, "does not match"
    yield "empty markdown", body("recommendation", "  ", tray), REC, "empty"
    yield "raw markup", body("recommendation", good + " <!-- td {x} -->", tray), REC, "markup"
    yield "tray on support", body("support", "Hi", tray), SUP, "tray has"
    yield "good support", body("support", "Track: https://track.example/x . Email care@bombayshavingcompany.com. Fee ₹99.", []), SUP, None
    yield "invented email", body("support", "Email help@bombayshavingcompany.com", []), SUP, "email"
    yield "order claim", body("support", "Your order has been shipped and is on its way.", []), SUP, "order"


def part_a() -> bool:
    ok = True
    for name, response, result, expect in cases():
        check = validate(response, result, CATALOG)
        passed = check.valid if expect is None else any(expect in c for c in check.critical)
        ok &= passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + ("" if passed else f" -> {check.critical}"))
    return ok


async def part_b() -> bool:
    from app.graph import memory_store
    from app.graph.builder import get_graph
    import app.graph.nodes.composer as composer_module
    from app.db.connection import close_pool, open_pool

    calls = []

    async def bad_llm(_model, messages):
        calls.append(messages)
        return SimpleNamespace(content="Buy **Totally Fake Razor** for ₹1 at https://evil.example/x")

    composer_module.ainvoke_with_429_retry = bad_llm
    memory_store.clear()
    await open_pool()
    try:
        state = await get_graph().ainvoke({"conversation_id": "check_b", "message": "Suggest a razor for sensitive skin"})
    finally:
        await close_pool()
    retry_prompt_mentions_issues = len(calls) == 2 and "rejected" in calls[1][1].content
    ok = len(calls) == 2 and state["response"].type == "fallback" and not state["response"].product_tray
    print(f"  composer calls={len(calls)} (expected 2), retry prompt had issues={retry_prompt_mentions_issues}, "
          f"final type={state['response'].type} (expected fallback)")
    return ok and retry_prompt_mentions_issues


def main() -> None:
    print("Part A: validator rules")
    a = part_a()
    print("Part B: forced bad composition -> one retry -> fallback")
    b = asyncio.run(part_b())
    print("\nRESULT:", "ALL PASS" if a and b else "FAILURES")
    sys.exit(0 if a and b else 1)


if __name__ == "__main__":
    main()
