"""scripts/check_comparison_table.py — prove the comparison table logic (offline).

Usage:  python -m scripts.check_comparison_table

No LLM, no database: fake product rows go through the real table builder, validator and history text.
"""

import sys

from app.graph.nodes.finalize import _history_text as ht
from app.response.comparison_table import build_comparison_table
from app.response.validator import validate
from app.schemas.chat import ChatResponseBody
from app.schemas.specialist import SpecialistOutput

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))


def row(pid, name, price, rating=4.5, reviews=10, stock="in_stock", original=None, desc="", features=None, benefits=None, specs=None):
    return {
        "id": pid, "name": name, "price": price, "original_price": original or price, "rating": rating,
        "review_count": reviews, "availability": stock, "category": "Hair Removal",
        "url": f"https://shop.example/{pid}", "image_url": f"https://img.example/{pid}.webp", "description": desc,
        "details": {"features": features or [], "specifications": specs or {}, "detailed_information": {"benefits": benefits or []}},
    }


def out(products, warnings=None) -> SpecialistOutput:
    return SpecialistOutput(specialist="comparison", status="success", data={"products": products}, warnings=warnings or [])


A = row("1", "Hair Removal Cream", 149, 4.88, 24, original=250, desc="Gentle cream.", benefits=["Painless", "Mess free"],
        features=["50g"], specs={"weight_grams": "50", "sku": "SKU_A", "barcode": "123", "options": "x"})
B = row("2", "Sports Spray", 499, 0, 0, stock="out_of_stock", desc="Fast spray.", benefits=["Athlete approved"],
        features=["200g"], specs={"weight_grams": "200", "sku": "SKU_B"})
C = row("3", "Sensi Spray", 749, 4.8, 5, desc="", benefits=["Gentle"], features=["200ml"], specs={})


def main() -> int:
    print("— structure —")
    t = build_comparison_table(out([A, B]))
    keys = [r.key for r in t.rows]
    check("two products -> two columns, rows in the fixed order",
          len(t.products) == 2 and keys[:6] == ["price", "availability", "rating", "description", "benefits", "features"], str(keys))
    check("every row has one cell per product", all(len(r.cells) == 2 for r in t.rows))
    check("price cell shows a real discount", t.rows[0].cells[0] == ["₹149", "was ₹250 · save 40%"] and t.rows[0].cells[1] == ["₹499"], str(t.rows[0].cells))
    check("availability text", t.rows[1].cells == [["In stock"], ["Currently out of stock"]])
    check("a 0.0 rating is 'No ratings yet'", t.rows[2].cells == [["4.88/5", "24 reviews"], ["No ratings yet"]], str(t.rows[2].cells))
    check("only the weight spec is shown, as '50 g'; sku/barcode/options never",
          [r.key for r in t.rows if r.key.startswith("spec:")] == ["spec:weight_grams"] and t.rows[-1].cells == [["50 g"], ["200 g"]], str(keys))
    check("a spec only one product has is not shown", all(not r.key.startswith("spec:") for r in build_comparison_table(out([A, C])).rows))

    t3 = build_comparison_table(out([A, B, C]))
    check("three products -> three columns", len(t3.products) == 3 and all(len(r.cells) == 3 for r in t3.rows))
    check("an empty description cell is [] (UI dash)", t3.rows[3].cells[2] == [])
    check("a row nobody has is dropped", all(r.key != "description" for r in build_comparison_table(out([row("4", "X", 1), row("5", "Y", 2)])).rows))
    check("four products are cut to three", len(build_comparison_table(out([A, B, C, row("4", "D", 9)])).products) == 3)
    check("one product -> no table", build_comparison_table(out([A])) is None)
    check("other specialists -> no table", build_comparison_table(SpecialistOutput(specialist="recommendation", status="success", data={"products": [A, B]})) is None)

    print("— validator —")
    result = out([A, B])
    good = ChatResponseBody(type="comparison", markdown="**Hair Removal Cream** is the gentler pick; **Sports Spray** is Currently out of stock.",
                            comparison_table=build_comparison_table(result))
    check("a correct reply passes", validate(good, result, []).valid, str(validate(good, result, []).critical))
    md = good.model_copy(update={"markdown": "| a | b |\n|---|---|\n| 1 | 2 |"})
    check("a Markdown table in the prose is rejected", not validate(md, result, []).valid)
    check("a missing table is rejected", not validate(good.model_copy(update={"comparison_table": None}), result, []).valid)
    bad = build_comparison_table(result)
    bad.products[0].price = 1.0
    check("a column with a wrong price is rejected", not validate(good.model_copy(update={"comparison_table": bad}), result, []).valid)
    short = build_comparison_table(out([A, B, C]))
    check("a table with the wrong product count is rejected", not validate(good.model_copy(update={"comparison_table": short}), result, []).valid)
    check("the tray stays empty for a comparison", good.product_tray == [])

    print("— history —")
    check("stored history names the compared products", ht(good) == "Compared: Hair Removal Cream (₹149), Sports Spray (₹499)", ht(good))

    print(f"\n{'ALL CHECKS PASSED' if not FAILED else str(FAILED) + ' CHECK(S) FAILED'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
