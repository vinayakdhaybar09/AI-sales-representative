"""scripts/check_reviewer.py — test the fulfilment reviewer before it is wired in.

Usage:
    python -m scripts.check_reviewer          # Part A only (offline, no LLM, no DB)
    python -m scripts.check_reviewer --live   # Part A + Part B (calls the Mistral chat model)

Part A: the pure helpers (which ids may be dropped, renumbering, warnings).
Part B: scenarios built from real conversations (dandruff, wooden comb,
        "compare the first two"). Each prints the reviewer's verdict next to
        what we expected, so you can judge false positives and misses.
"""

import argparse
import asyncio
import sys

from app.core.logging import setup_logging
from app.graph.nodes.reviewer import get_review
from app.response.review import apply_exclusions, clean_exclusions, issues_to_text, should_review
from app.schemas.review import Review, ReviewIssue
from app.schemas.specialist import SpecialistOutput

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"   ({detail})" if detail and not ok else ""))


def product(pid, name, price, description, rating=4.5, reviews=50, features=None, category="Skin care"):
    return {
        "id": pid, "name": name, "price": price, "original_price": price, "availability": "in_stock",
        "rating": rating, "review_count": reviews, "category": category, "description": description,
        "details": {"features": features or []},
    }


def out(specialist, products=None, **data):
    return SpecialistOutput(
        specialist=specialist, status="success", data={"products": products or [], **data},
        sources=[{"type": "product", "id": p["id"], "name": p["name"]} for p in products or []],
    )


# ───────── Part A ─────────
def part_a() -> None:
    print("Part A: pure helpers (offline)")
    items = [product("1", "A", 100, "a"), product("2", "B", 200, "b"), product("3", "C", 300, "c")]
    rec = out("recommendation", items)
    review = Review(fulfils=False, issues=[ReviewIssue(kind="irrelevant", detail="A is unrelated")], exclude_item_ids=["1", "9", "1"])

    check("only ids that exist are kept, duplicates removed", clean_exclusions(review, rec) == ["1"])
    check("comparison never loses products", clean_exclusions(review, out("comparison", items)) == [])
    check("knowledge has no products to drop", clean_exclusions(review, out("knowledge")) == [])

    trimmed = apply_exclusions(rec, ["1"])
    check("excluded product is removed from data and sources",
          [p["id"] for p in trimmed.data["products"]] == ["2", "3"] and [s["id"] for s in trimmed.sources] == ["2", "3"])
    check("original result is untouched", len(rec.data["products"]) == 3)
    check("no warning while products remain", "no_suitable_products" not in trimmed.warnings)

    empty = apply_exclusions(rec, ["1", "2", "3"])
    check("nothing left -> warning no_suitable_products", empty.data["products"] == [] and "no_suitable_products" in empty.warnings)

    fin = out("product_finalization", [dict(items[0], rank=1), dict(items[1], rank=2)])
    check("finalization ranks are renumbered", [p["rank"] for p in apply_exclusions(fin, ["1"]).data["products"]] == [1])
    check("comparison result is returned unchanged", apply_exclusions(out("comparison", items), ["1"]).data["products"] == items)

    check("feedback lines name the issue kind", issues_to_text(review) == ["Reviewer (irrelevant): A is unrelated"])
    check("success results of the five kinds are reviewed",
          all(should_review(out(s)) for s in ("recommendation", "product_finalization", "comparison", "knowledge", "support")))
    check("empty and error results are not reviewed",
          not should_review(SpecialistOutput(specialist="recommendation", status="empty"))
          and not should_review(SpecialistOutput(specialist="support", status="error")))


# ───────── Part B ─────────
SKIN = [
    product("p1", "1% salicylic body wash, 200 ml", 499, "Unclogs pores and clears bumps for soft, radiant skin with 1% salicylic acid."),
    product("p2", "Charcoal Face Scrub, 100g", 299, "Deep cleans pores and eliminates blackheads with activated charcoal."),
    product("p3", "Neem and Charcoal Bath Soap, 75g", 88, "Kills 99.9% germs and bacteria while purifying skin with neem and charcoal."),
    product("p4", "Daily Detan Face Wash 50g", 149, "Removes tan and dullness with coffee extracts and vitamin C beads."),
    product("p5", "Activated Charcoal Face Wash 100ml", 189, "Cleanses oil and dirt from the face with activated charcoal."),
]
COMB = [product("c1", "Hair Comb White", 50, "A lightweight, curved-handle comb with fine teeth for neat styling.", 4.6, 45, category="Accessories")]
RAZORS = [
    product("r1", "Sensi Smart 3 Razor", 199, "Three-blade razor for sensitive skin.", 4.7, 300, ["Lubrication strip", "Pivoting head"], "Razors"),
    product("r2", "Legend Razor", 299, "Five-blade razor with a weighted handle.", 4.5, 120, ["Weighted handle", "Five blades"], "Razors"),
]
DANDRUFF_HISTORY = [
    {"role": "user", "content": "i have so much dandruff, how can i get rid off?"},
    {"role": "assistant", "content": "Shampoo regularly, avoid over-oiling, manage stress. Read the full article: 6 Reasons Why Your Dandruff Treatment Isn't Working?"},
]
RAZOR_HISTORY = [
    {"role": "user", "content": "suggest a razor"},
    {"role": "assistant", "content": "Showed products: Sensi Smart 3 Razor (₹199), Legend Razor (₹299)"},
]

# (name, request, requirements, history, result, reply, expect_fulfils, expect_excluded_ids)
SCENARIOS = [
    ("dandruff: unrelated skin products sold as help", "Suggest a product for dandruff", ["dandruff"], DANDRUFF_HISTORY,
     out("recommendation", SKIN),
     "Here are some products that may help with your skin concerns:\n- **1% salicylic body wash, 200 ml** – ₹499: Unclogs pores.\n"
     "- **Charcoal Face Scrub, 100g** – ₹299: Deep cleans pores.\n- **Neem and Charcoal Bath Soap, 75g** – ₹88: Kills germs.\n"
     "- **Daily Detan Face Wash 50g** – ₹149: Removes tan.",
     False, {"p1", "p2", "p3", "p4"}),
    ("dandruff: honest answer with a labelled alternative", "Suggest a product for dandruff", ["dandruff"], DANDRUFF_HISTORY,
     out("recommendation", SKIN),
     "We don't have a product made for scalp dandruff, so I won't point you to one that isn't. If the flakes are in your beard, "
     "the **Charcoal Face Scrub, 100g** (₹299) is a cleanser that deep cleans pores with activated charcoal, so it could help keep "
     "the area clean. For the scalp, the tips above are the best bet for now.",
     True, set()),
    ("wooden comb: honest about the gap", "Show a wooden hair comb", ["hair comb", "wooden"], [],
     out("recommendation", COMB),
     "We don't have a wooden comb right now. The closest is the **Hair Comb White** – ₹50: a lightweight comb with fine teeth, "
     "handy for neat styling.",
     True, set()),
    ("wooden comb: pretends the white comb is wooden", "Show a wooden hair comb", ["hair comb", "wooden"], [],
     out("recommendation", COMB),
     "Here's a wooden hair comb for you:\n- **Hair Comb White** – ₹50: a lightweight, curved-handle wooden comb with fine teeth.",
     False, set()),
    ("scalp claim not in the description", "Suggest something to exfoliate", ["exfoliate"], [],
     out("recommendation", SKIN[:1]),
     "The **1% salicylic body wash, 200 ml** – ₹499 exfoliates and soothes irritated skin, including the scalp.",
     False, set()),
    ("compare the first two: both covered", "Compare Sensi Smart 3 Razor and Legend Razor",
     ["compare Sensi Smart 3 Razor", "compare Legend Razor"], RAZOR_HISTORY,
     out("comparison", RAZORS),
     "| | Sensi Smart 3 Razor | Legend Razor |\n|---|---|---|\n| Price | ₹199 | ₹299 |\n| Rating | 4.7 | 4.5 |\n"
     "| Features | Lubrication strip, pivoting head | Weighted handle, five blades |\n\nThe Sensi is the cheaper and slightly higher-rated pick; the Legend has the weighted handle and five blades.",
     True, set()),
    ("compare: claim not in the evidence", "Compare Sensi Smart 3 Razor and Legend Razor",
     ["compare Sensi Smart 3 Razor", "compare Legend Razor"], RAZOR_HISTORY,
     out("comparison", RAZORS),
     "| | Sensi Smart 3 Razor | Legend Razor |\n|---|---|---|\n| Price | ₹199 | ₹299 |\n| Rating | 4.7 | 4.5 |\n\n"
     "The Legend is dermatologist tested and gives a closer shave.",
     False, set()),
    ("compare the first two: only one covered", "Compare Sensi Smart 3 Razor and Legend Razor",
     ["compare Sensi Smart 3 Razor", "compare Legend Razor"], RAZOR_HISTORY,
     out("comparison", RAZORS),
     "The **Sensi Smart 3 Razor** costs ₹199, is rated 4.7 and has a lubrication strip and a pivoting head.",
     False, set()),
    ("plain request answered well", "Suggest a face wash under 200", ["face wash", "under 200"], [],
     out("recommendation", [SKIN[3], SKIN[4]]),
     "Here are two face washes under ₹200:\n- **Daily Detan Face Wash 50g** – ₹149: removes tan and dullness with coffee extracts and vitamin C beads.\n"
     "- **Activated Charcoal Face Wash 100ml** – ₹189: cleanses oil and dirt from the face with activated charcoal.",
     True, set()),
]


async def part_b() -> None:
    print("\nPart B: live reviewer scenarios (Mistral)")
    wrong = 0
    for name, request, reqs, history, result, reply, expect_fulfils, expect_ids in SCENARIOS:
        try:
            review = await get_review(request, reqs, history, result, reply)
        except Exception as exc:
            print(f"  [ERROR] {name}: {type(exc).__name__}: {exc}")
            wrong += 1
            continue
        excluded = set(clean_exclusions(review, result))
        ok = review.fulfils == expect_fulfils and (not expect_ids or excluded >= expect_ids)
        wrong += 0 if ok else 1
        print(f"  [{'AS EXPECTED' if ok else 'DIFFERENT'}] {name}")
        print(f"      expected fulfils={expect_fulfils}" + (f", exclude {sorted(expect_ids)}" if expect_ids else ""))
        print(f"      got      fulfils={review.fulfils}, excluded={sorted(excluded)}")
        for line in issues_to_text(review):
            print(f"      - {line}")
    print(f"\n{len(SCENARIOS) - wrong}/{len(SCENARIOS)} scenarios as expected (judge the DIFFERENT ones by reading the verdict).")


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="also run Part B against the real chat model")
    args = parser.parse_args()
    part_a()
    if args.live:
        asyncio.run(part_b())
    print(f"\n{'PART A PASSED' if not FAILED else str(FAILED) + ' PART A CHECK(S) FAILED'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
