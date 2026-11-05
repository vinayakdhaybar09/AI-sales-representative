"""scripts/check_product_detail.py — the product detail mapping, on every product in the data file (offline).

Usage:  python -m scripts.check_product_detail
"""

import json
import re
import sys

from app.db.repositories.products import _build_details
from app.response.product_detail import build_product_detail

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"   ({detail})" if detail else ""))


def rows():
    data = json.load(open("data/bombay-shaving-product-data.json"))
    for category in data["categories"]:
        for p in category["products"]:
            yield {
                "id": p["id"], "category": p["category"], "name": p["name"], "url": p["url"], "image_url": p["image_url"],
                "description": p["description"], "price": p["price"], "original_price": p["original_price"],
                "rating": p["rating"], "review_count": p["review_count"],
                "availability": (p["availability"] or {}).get("status", "out_of_stock"), "details": _build_details(p),
            }


def main() -> int:
    all_rows = list(rows())
    details = [build_product_detail(r) for r in all_rows]
    print(f"Mapped {len(details)} products without errors")
    check("every product has a main image first", all(d.images and d.images[0] == r["image_url"] for d, r in zip(details, all_rows)))
    check("most products have a gallery (2+ images)", sum(len(d.images) >= 2 for d in details) >= 190, str(sum(len(d.images) >= 2 for d in details)))
    check("no more than 12 images, no duplicates", all(len(d.images) <= 12 and len(set(d.images)) == len(d.images) for d in details))
    check("price, availability and URL come from the row", all(d.price == float(r["price"]) and d.availability == r["availability"] and d.product_url == r["url"] for d, r in zip(details, all_rows)))
    check("rating is null without reviews (never 0)", all((d.rating is None) == (not (r["review_count"] or 0) or not (r["rating"] or 0)) for d, r in zip(details, all_rows)))
    check("original price only when it is a real discount", all(d.original_price is None or d.original_price > d.price for d in details))
    texts = [t for d in details for t in [d.description or "", d.about or "", *d.key_features, *d.how_to_use,
             *(s.text for s in d.other_information), *(f.answer for f in d.faqs)]]
    check("no HTML or CSS comment markup in any text", not any(re.search(r"<!--|</?[a-z][^>]*>", t) for t in texts))
    check("no emoji in any text", not any(re.search("[\U0001F300-\U0001FAFF☀-➿]", t) for t in texts))
    check("usage steps carry no '1)' numbering", not any(re.match(r"\s*\d+[.)]", s) for d in details for s in d.how_to_use))
    check("features exist for most products", sum(bool(d.key_features) for d in details) >= 165, str(sum(bool(d.key_features) for d in details)))
    check("how-to-use steps exist for the products that have them", sum(bool(d.how_to_use) for d in details) >= 55, str(sum(bool(d.how_to_use) for d in details)))
    check("about text is never the same as the description", all(not d.about or d.about != d.description for d in details))
    cool = next(d for d in details if d.name == "Cool Detox Face Wash 50g")
    check("sample: Cool Detox Face Wash has features, 5 steps, an FAQ and images",
          len(cool.key_features) == 6 and len(cool.how_to_use) == 5 and cool.faqs and len(cool.images) >= 2, str(cool.how_to_use[:1]))
    print(f"\n{'ALL PRODUCT DETAIL CHECKS PASSED' if not FAILED else str(FAILED) + ' CHECK(S) FAILED'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
