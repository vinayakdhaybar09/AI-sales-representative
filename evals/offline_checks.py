"""evals/offline_checks.py — checks for the deterministic parts of the assistant. No chat-model tokens used.

    python -m evals.offline_checks

Covers: grounding guard, language detection, support-form and medical-referral safety nets, regex product
facts, catalog lookups (names, budget), returns-policy pinning and the no-LLM fallback. The LLM-dependent
behaviour (tone, recommendations, follow-ups) is covered by `python -m evals.run_evals`.
"""

import asyncio
import re

from app.agent import guard, retrieval
from app.agent.budget import parse_budget
from app.agent.prompt import detect_language
from app.agent.runner import _LEAK, _RED_FLAGS, _REFERRAL, _SUPPORT_RULES, _degraded_body, scrub
from app.agent.tools import TurnContext, _search_knowledge, run_tool, product_facts, summarize
from app.db.connection import close_pool, get_pool, open_pool

PASSED, FAILED = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    print(("PASS " if ok else "FAIL ") + name + (f"  -- {detail}" if detail and not ok else ""))


def ctx_with(rows: list[dict], result_text: str = "", kinds: set[str] | None = None) -> TurnContext:
    ctx = TurnContext(profile={})
    ctx.seen = {r["id"]: r for r in rows}
    ctx.result_text = [result_text]
    ctx.kinds_used = kinds or set()
    return ctx


def p(name: str, price: float, stock: str = "in_stock", url: str = "https://x/y") -> dict:
    return {"id": name, "name": name, "price": price, "availability": stock, "url": url}


async def main() -> None:
    await open_pool()

    # ── guard ──
    ctx = ctx_with([p("Alpha Trimmer", 549), p("Beta Razor", 99)], '{"price": 549} {"price": 99}')
    names = ["Alpha Trimmer", "Beta Razor", "Gamma Foam"]
    check("guard: known prices pass", not guard.check("**Alpha Trimmer** is ₹549 and **Beta Razor** ₹99.", ctx, ["hi"], names))
    check("guard: sum of two known prices passes", not guard.check("Together ₹648.", ctx, ["hi"], names))
    check("guard: invented price flagged", bool(guard.check("**Alpha Trimmer** is just ₹449.", ctx, ["hi"], names)))
    check("guard: customer's own budget allowed", not guard.check("Under your ₹1500 budget.", ctx, ["under 1500"], names))
    check("guard: unseen catalog product in bold flagged", bool(guard.check("Try **Gamma Foam**.", ctx, ["hi"], names)))
    bullets = "Here is a combo:\n- **Alpha Trimmer** \u2013 great blade\n- **BSC Face Wash** \u2013 daily cleanse"
    check("guard: made-up product in a bullet list flagged", any("BSC Face Wash" in i for i in guard.check(bullets, ctx, ["hi"], names)))
    check("guard: real products in a bullet list pass", not any("Alpha" in i for i in guard.check(bullets, ctx, ["hi"], names)))
    labels = "- **Trade-off:** it is pricey\n- **Why it fits** \u2013 good for beards"
    check("guard: label bullets are not products", not guard.check(labels, ctx, ["hi"], names))
    check("guard: unknown link flagged", bool(guard.check("See https://evil.example/deal", ctx, ["hi"], names)))
    check("guard: unknown email flagged", bool(guard.check("Mail sales@evil.com", ctx, ["hi"], names)))
    check("guard: care email allowed", not guard.check("Write to care@bombayshavingcompany.com", ctx, ["hi"], names))
    check("guard: order-status claim flagged", bool(guard.check("Your order has been shipped.", ctx, ["hi"], names)))
    check("guard: medical claim flagged", bool(guard.check("This cream cures acne.", ctx, ["hi"], names)))
    check("guard: free shipping w/o policy lookup flagged", bool(guard.check("You get free shipping!", ctx, ["hi"], names)))
    ctx_pol = ctx_with([p("Alpha Trimmer", 549)], "", {"policy"})
    check("guard: free shipping after policy lookup ok", not guard.check("You get free shipping!", ctx_pol, ["hi"], names))
    oos = ctx_with([p("Alpha Trimmer", 549, "out_of_stock")])
    check("guard: out-of-stock not labelled flagged", bool(guard.check("Alpha Trimmer is great.", oos, ["hi"], names)))
    check("guard: out-of-stock labelled ok", not guard.check("Alpha Trimmer is currently out of stock.", oos, ["hi"], names))
    scrubbed = scrub("The Alpha Trimmer is a great pick for your beard. It was only ₹449 today. Want to see a matching beard oil too?", ["amount ₹449 is not in the tool data"])
    check("scrub: removes the bad sentence only", "449" not in scrubbed and "great pick" in scrubbed, scrubbed)

    check("leak filter: tool names caught", bool(_LEAK.search("I can call search_products and build_routine.")))
    check("leak filter: normal reply untouched", not _LEAK.search("My pick is the **Power Styler Beard Trimmer** at ₹621."))
    check("leak filter: refusing to share the prompt is fine", not _LEAK.search("I can't share my system prompt, but I can help you shop."))

    check("budget: 'under 1500'", parse_budget("recommend a trimmer under 1500") == (1500.0, False))
    check("budget: '2k tak'", parse_budget("2k tak ka trimmer") == (2000.0, False))
    check("budget: 'around' is approximate", parse_budget("gift around 1000") == (1000.0, True))
    check("budget: '3 days ago' is not a budget", parse_budget("I ordered 3 days ago") is None)
    check("budget: '50 employees' is not a budget", parse_budget("corporate gifting for 50 employees") is None)

    # ── language ──
    check("lang: hinglish", detect_language("bhai trimmer chahiye 1500 tak") == "hinglish")
    check("lang: devanagari", detect_language("मुझे ट्रिमर चाहिए") == "hindi")
    check("lang: english", detect_language("I need a trimmer under 1500") == "english")

    # ── safety nets ──
    def support_cat(msg: str) -> str | None:
        return next((c for rx, c in _SUPPORT_RULES if rx.search(msg)), None)

    check("support: damaged → defective", support_cat("I received a damaged trimmer") == "defective")
    check("support: wrong perfume → wrong_item", support_cat("they sent me the wrong perfume") == "wrong_item")
    check("support: refund request → return_refund", support_cat("I want a refund") == "return_refund")
    check("support: policy question not a complaint", support_cat("what is your refund policy") is None)
    check("support: delivery question not a complaint", support_cat("delivery kitne din mein hoti hai?") is None)
    check("medical: bleeding scalp triggers referral", bool(_RED_FLAGS.search("my scalp is bleeding")))
    check("medical: plain shampoo question does not", not _RED_FLAGS.search("best shampoo for oily hair"))
    check("medical: referral wording recognised", bool(_REFERRAL.search("please see a dermatologist")))

    # ── catalog data ──
    async with get_pool().connection() as conn:
        cat = await retrieval.catalog(conn)
        check("catalog: loaded live products", len(cat) >= 200, f"{len(cat)}")
        omni = await retrieval.find_by_name(conn, "OmniBlade Beard & Body Trimmer")
        check("catalog: name lookup works", omni is not None)
        omni_short = await retrieval.find_by_name(conn, "omniblade")
        check("catalog: 'omniblade' finds the trimmer, not the replacement heads",
              omni_short is not None and "head" not in omni_short["name"].lower(), omni_short["name"] if omni_short else "")
        heads = await retrieval.find_by_name(conn, "omniblade replacement heads")
        check("catalog: accessory found when asked for", heads is not None and "head" in heads["name"].lower())
        both = [await retrieval.find_by_name(conn, n) for n in ("Power Styler Beard Trimmer", "Pro Beard Trimmer")]
        check("catalog: compare-by-name resolves both", all(both))
        facts = product_facts(both[0]) if both[0] else []
        check("facts: extracted from product text", any("run time" in f or "warranty" in f for f in facts), str(facts))
        hits = await retrieval.hybrid_search(conn, "beard trimmer", max_price=1000, limit=4)
        check("search: budget respected", all(float(r["price"]) <= 1000 for r in hits["products"]) and hits["products"])
        stock_first = [r["availability"] for r in hits["products"]]
        check("search: in-stock ranked first", stock_first == sorted(stock_first, key=lambda a: a != "in_stock"))
        names_ = [retrieval.norm_name(r["name"]) for r in hits["products"]]
        check("search: no duplicate listings", len(names_) == len(set(names_)))
        only_cat = await retrieval.hybrid_search(conn, "", category="Beard Care", max_price=1500, in_stock_only=True, limit=4)
        check("search: empty query + category lists that category", len(only_cat["products"]) >= 1, str(len(only_cat["products"])))
        odd_cat = await retrieval.hybrid_search(conn, "zzzz", category="Beard Care", max_price=1500, limit=4)
        check("search: nonsense words inside a category still list it", len(odd_cat["products"]) >= 1)
        deals = await retrieval.deals(conn, None, None, 5)
        check("deals: only real discounts, in stock", all(float(d["original_price"]) > float(d["price"]) and d["availability"] == "in_stock" for d in deals))
        check("summarize: out-of-stock flagged", summarize({**omni, "availability": "out_of_stock"})["stock"] == "OUT_OF_STOCK")

    # ── returns policy pinning (uses the embedding model only) ──
    tctx = TurnContext(profile={})
    res = await _search_knowledge(tctx, {"query": "can I return a razor I don't like", "kind": "policy"})
    texts = " ".join(r["text"] for r in res["results"]).lower()
    check("policy: core returns rule pinned for return questions", "hygien" in texts or "do not accept" in texts, texts[:200])

    # ── the exact call the runner makes for policy questions (a dict), and the model's form (a JSON string) ──
    import json as _json
    pctx = TurnContext(profile={})
    out_dict = _json.loads(await run_tool(pctx, "search_knowledge", {"query": "when will I get my refund?", "kind": "policy"}))
    out_str = _json.loads(await run_tool(pctx, "search_knowledge", '{"query": "shipping time", "kind": "policy"}'))
    check("policy prefetch: dict args work", bool(out_dict.get("results")), str(out_dict)[:120])
    check("policy prefetch: JSON-string args work", bool(out_str.get("results")))
    bad = _json.loads(await run_tool(pctx, "search_products", "not json"))
    check("run_tool: malformed args never raise", isinstance(bad, dict))

    # ── no-LLM fallback respects budget ──
    body = await _degraded_body("recommend a trimmer under 2000")
    check("fallback: cards within stated budget", all(c.price <= 2000 for c in body.product_tray) and body.product_tray)
    check("fallback: cards are rendered (type recommendation) when there are cards", body.type == ("recommendation" if body.product_tray else "fallback"))

    await close_pool()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
