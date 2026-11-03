"""scripts/check_finalization.py — prove the product_finalization logic (offline).

Usage:  python -m scripts.check_finalization

No LLM, no database: fake product rows go through the real selection, memory,
sufficiency, tray and validator code. Every line prints PASS or FAIL.
"""

import sys

from app.graph import preferences
from app.graph.builder import get_graph
from app.graph.nodes.sufficiency import check_sufficiency
from app.llm.prompts.composer import serialise
from app.response.tray import build_tray
from app.response.validator import validate
from app.schemas.chat import ChatResponseBody
from app.schemas.query import Context, Entities, Filters, QueryUnderstanding
from app.schemas.specialist import SpecialistOutput
from app.specialists.finalization import requested_count, select

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))


def row(pid, name, price, rating, reviews, stock="in_stock", desc="A product.", features=None, benefits=None, how=None):
    return {
        "id": pid, "name": name, "price": price, "original_price": price, "rating": rating,
        "review_count": reviews, "availability": stock, "category": "Trimmers",
        "url": f"https://shop.example/{pid}", "image_url": f"https://img.example/{pid}.webp",
        "description": desc,
        "details": {"features": features or [], "detailed_information": {"benefits": benefits or [], "how_to_use": how or []}},
    }


def q(intent="product_finalization", **kw) -> QueryUnderstanding:
    return QueryUnderstanding(
        intent=intent, scope="in_scope",
        entities=Entities(**kw.get("entities", {})), filters=Filters(**kw.get("filters", {})),
        context=Context(**kw.get("context", {})),
    )


POOL = [
    row("1", "Alpha Trimmer", 499, 4.9, 2),                                  # 5-star but only 2 reviews
    row("2", "Beta Trimmer", 599, 4.7, 300, features=["Waterproof body", "Beard length settings"]),
    row("3", "Gamma Trimmer", 250, 4.2, 80),
    row("4", "Delta Trimmer", 450, 4.8, 500, stock="out_of_stock"),          # best rated but unavailable
]
SCORES = {"1": 0.80, "2": 0.78, "3": 0.74, "4": 0.82}


def main() -> int:
    print("— selection —")
    picked, warns, basis = select(POOL, SCORES, q(), 1)
    check("default pick is the review-weighted best, not the 2-review 5-star", picked[0]["id"] == "2", picked[0]["name"])
    check("out-of-stock product (best rated) is skipped", all(p["id"] != "4" for p in picked))
    check("one product asked, one returned, rank 1", len(picked) == 1 and picked[0]["rank"] == 1)
    check("reasons are present and factual", any("rated 4.7/5 from 300 reviews" in r for r in picked[0]["selection_reasons"]),
          str(picked[0]["selection_reasons"]))

    picked, warns, _ = select(POOL, SCORES, q(filters={"result_limit": 3}), 3)
    check("shortlist returns 3 ranked 1-3", [p["rank"] for p in picked] == [1, 2, 3])
    check("shortlist never pads with the out-of-stock one", {p["id"] for p in picked} == {"1", "2", "3"})

    picked, warns, _ = select(POOL, SCORES, q(filters={"budget_max": 300}), 1)
    check("budget under 300 picks Gamma (only one that fits)", [p["id"] for p in picked] == ["3"])
    check("reason mentions the budget", any("within your ₹300 budget" in r for r in picked[0]["selection_reasons"]))

    picked, _, basis = select(POOL, SCORES, q(filters={"priority": "lowest_price"}), 1)
    check("priority lowest_price picks the cheapest in stock", picked[0]["id"] == "3" and basis == "priority")

    picked, _, _ = select(POOL, SCORES, q(filters={"priority": "highest_rated"}), 1)
    check("priority highest_rated ignores out-of-stock and tiny samples", picked[0]["id"] == "2", picked[0]["name"])

    picked, _, _ = select(POOL, SCORES, q(entities={"use_case": ["waterproof"]}), 1)
    check("stated need in product text boosts that product", picked[0]["id"] == "2")

    picked, _, _ = select(POOL, SCORES, q(filters={"exclusions": ["alpha", "beta"]}), 3)
    check("exclusions remove products by name", {p["id"] for p in picked} == {"3"})

    picked, warns, _ = select([POOL[3]], SCORES, q(), 1)
    check("only out-of-stock qualifies -> returned with warning", picked and "selected_out_of_stock" in warns)

    picked, warns, _ = select(POOL, SCORES, q(filters={"budget_max": 100}), 1)
    check("nothing within budget -> empty list (caller widens the search)", picked == [])

    check("result_limit defaults to 1", requested_count(q()) == 1)
    check("result_limit is capped at 3", requested_count(q(filters={"result_limit": 9})) == 3)

    print("— structured memory —")
    p1 = preferences.merge({}, q("recommendation", entities={"category": "Trimmer", "use_case": ["beard_grooming"]},
                                 filters={"budget_max": 2000, "skin_type": ["sensitive"]}))
    check("first turn is remembered", p1["category"] == "trimmer" and p1["budget_max"] == 2000 and p1["skin_type"] == ["sensitive"])
    p2 = preferences.merge(p1, q("recommendation", filters={"skin_type": ["Sensitive", "dry"]}))
    check("lists add without duplicates", p2["skin_type"] == ["sensitive", "dry"], str(p2["skin_type"]))
    p3 = preferences.merge(p2, q("product_finalization"))
    check("a message with no new info changes nothing", p3 == p2)
    p4 = preferences.merge(p2, q("recommendation", entities={"category": "face wash"}))
    check("new category resets the need (budget, use) but keeps skin type",
          "budget_max" not in p4 and "use_case" not in p4 and p4["skin_type"] == ["sensitive", "dry"] and p4["category"] == "face wash")
    filled = preferences.apply_to_query(q(filters={"budget_max": 300}), p2)
    check("memory fills gaps; what the user says now wins", filled.filters.budget_max == 300 and filled.filters.skin_type == ["sensitive", "dry"]
          and filled.entities.category == "trimmer")

    print("— sufficiency —")
    check("finalization with products already shown: sufficient",
          check_sufficiency(q(context={"previously_mentioned_product_ids": ["1", "2"]})) == (True, None))
    check("finalization with no pool and no category: asks for category",
          check_sufficiency(q()) == (False, "category"))
    check("finalization with no pool but a category: sufficient (no forced question)",
          check_sufficiency(q(entities={"category": "face wash"}))[0] is True)
    check("finalization with no pool, 'trimmer', no use case: asks use_case",
          check_sufficiency(q(entities={"category": "trimmer"})) == (False, "use_case"))

    print("— tray + validator —")
    picked, warns, _ = select(POOL, SCORES, q(filters={"result_limit": 2}), 2)
    result = SpecialistOutput(specialist="product_finalization", status="success",
                              data={"products": picked, "criteria_applied": ["product type: trimmer"], "requested": 2}, warnings=warns)
    tray = build_tray(result)
    check("tray has the picks in rank order with featured fields",
          [c.rank for c in tray] == [1, 2] and tray[0].description and tray[0].selection_reasons)
    check("benefits fall back to features when there are no benefits", tray[0].key_benefits == ["Waterproof body", "Beard length settings"],
          str(tray[0].key_benefits))
    md = f"Go with **{picked[0]['name']}** at ₹{picked[0]['price']:g}. Also **{picked[1]['name']}** at ₹{picked[1]['price']:g}."
    good = ChatResponseBody(type="product_finalization", markdown=md, product_tray=tray)
    check("a correct response passes the validator", validate(good, result, [r["name"] for r in POOL]).valid)
    bad = ChatResponseBody(type="product_finalization", markdown=md, product_tray=tray[:1])
    check("a tray with a missing pick is rejected", not validate(bad, result, []).valid)
    mixed = ChatResponseBody(type="product_finalization", markdown=md + " Or **Gamma Trimmer**.", product_tray=tray)
    check("mentioning a product that was not picked is rejected", not validate(mixed, result, [r["name"] for r in POOL]).valid)
    rec = SpecialistOutput(specialist="recommendation", status="success", data={"products": POOL[:2]})
    check("recommendation cards carry no featured fields", build_tray(rec)[0].rank is None and build_tray(rec)[0].key_benefits == [])
    check("composer data shows rank and reasons", '"rank": 1' in serialise(result) and "customer_needs" in serialise(result))

    print("— validator: invented time periods —")
    sup = SpecialistOutput(specialist="support", status="success",
                           data={"items": [{"content": "Orders ship within 7-10 business days. Refunds take 5 days."}], "contact_info": {}})
    ok = ChatResponseBody(type="support", markdown="Orders ship within 7-10 business days, and refunds take 5 days.")
    bad = ChatResponseBody(type="support", markdown="Orders usually ship in 2-3 business days.")
    check("a support period that is in the data passes", validate(ok, sup, []).valid)
    check("an invented support period is critical", not validate(bad, sup, []).valid)
    rec2 = SpecialistOutput(specialist="recommendation", status="success", data={"products": POOL[:1]})
    note = validate(ChatResponseBody(type="recommendation", markdown="**Alpha Trimmer** ₹499, ready in 3 days.", product_tray=build_tray(rec2)), rec2, [])
    check("elsewhere an invented period is only a note", note.valid and any("time period" in n for n in note.non_critical), str(note.non_critical))

    echo = ChatResponseBody(type="recommendation", markdown="**Alpha Trimmer** at ₹499 is within ₹700.", product_tray=build_tray(rec2))
    check("an amount only the customer typed is rejected without the request", not validate(echo, rec2, []).valid)
    check("...and accepted when it is in the customer's request", validate(echo, rec2, [], "a trimmer under 700").valid)

    print("— graph —")
    nodes = set(get_graph().get_graph().nodes)
    check("graph compiles with specialist_product_finalization", "specialist_product_finalization" in nodes, str(sorted(nodes)))

    print(f"\n{'ALL CHECKS PASSED' if not FAILED else str(FAILED) + ' CHECK(S) FAILED'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
