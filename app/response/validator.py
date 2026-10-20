"""app/response/validator.py — deterministic check of a composed response.

No LLM and no network: pure Python. It compares the response with the
specialist output (the ground truth) and returns critical issues (these
trigger the one Composer retry) and non-critical notes (logged only).

Limits (by design): it catches wrong prices, URLs and emails, products from
outside the specialist result, missing out-of-stock wording, order-specific
claims and raw markup. It cannot prove that every sentence is grounded.
"""

import json
import re
from dataclasses import dataclass, field

from app.schemas.chat import ChatResponseBody
from app.schemas.specialist import SpecialistOutput

_AMOUNT = re.compile(r"(?:₹|\bRs\.?|\bINR)\s?(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_URL = re.compile(r"https?://[^\s)\]>\"'<]+")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MARKUP = re.compile(r"<!--|-->|<\s*/?\s*(?:style|script|td|tr|table|div|span|p|br)\b", re.IGNORECASE)
_ORDER_CLAIM = re.compile(
    r"\byour (?:order|package|parcel|shipment|refund|payment|replacement)\b[^.\n]{0,40}?"
    r"\b(?:has been|have been|is currently|is being|is on its way|is out for|"
    r"was (?:shipped|delivered|dispatched)|will arrive|arrives)\b",
    re.IGNORECASE,
)
OUT_OF_STOCK_PHRASE = "currently out of stock"
MAX_MARKDOWN_CHARS = 4000


@dataclass
class ValidationResult:
    critical: list[str] = field(default_factory=list)
    non_critical: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.critical


def _float(text: str) -> float:
    return float(text.replace(",", ""))


def _clean_url(url: str) -> str:
    return url.rstrip(".,;:!?")


def _check_tray(response: ChatResponseBody, result: SpecialistOutput, out: ValidationResult) -> None:
    expected = result.data.get("products", []) if result.specialist == "recommendation" else []
    tray = response.product_tray
    if len(tray) != len(expected):
        out.critical.append(f"tray has {len(tray)} products but the specialist returned {len(expected)}")
        return
    for card, product in zip(tray, expected):
        problems = []
        if card.product_id != str(product["id"]):
            problems.append("product_id")
        if card.name != product["name"]:
            problems.append("name")
        if card.price != float(product["price"]):
            problems.append("price")
        if card.image_url != (product.get("image_url") or ""):
            problems.append("image_url")
        if card.product_url != (product.get("url") or ""):
            problems.append("product_url")
        if card.availability != product["availability"]:
            problems.append("availability")
        if problems:
            out.critical.append(f"tray card '{card.name}' differs from specialist data: {', '.join(problems)}")


def validate(
    response: ChatResponseBody,
    result: SpecialistOutput,
    catalog_names: list[str],
) -> ValidationResult:
    out = ValidationResult()
    md = response.markdown or ""
    low = md.lower()
    data_text = json.dumps(result.data, ensure_ascii=False) + json.dumps(result.sources, ensure_ascii=False)

    # 1. structure
    if response.type != result.specialist:
        out.critical.append(f"response type '{response.type}' does not match the '{result.specialist}' specialist")
    if not md.strip():
        out.critical.append("markdown is empty")
    if len(md) > MAX_MARKDOWN_CHARS:
        out.non_critical.append(f"markdown is long ({len(md)} chars)")
    if _MARKUP.search(md):
        out.critical.append("markdown contains raw HTML/CSS markup copied from the data")

    # 2. tray
    _check_tray(response, result, out)

    # 3. amounts: every price quoted must exist in the specialist data
    allowed_numbers = {_float(n) for n in _NUMBER.findall(data_text)}
    for amount in _AMOUNT.findall(md):
        if _float(amount) not in allowed_numbers:
            out.critical.append(f"amount ₹{amount} does not appear in the specialist data")

    # 4. URLs: unknown URLs are invented; product URLs/images belong in the tray, not prose
    product_urls = set()
    for p in result.data.get("products", []):
        product_urls.add(p.get("url"))
        product_urls.add(p.get("image_url"))
        product_urls.update(p.get("details", {}).get("images", []) or [])
    known_urls = {_clean_url(u) for u in _URL.findall(data_text)}
    for url in {_clean_url(u) for u in _URL.findall(md)}:
        if url in product_urls:
            out.non_critical.append("a product URL/image appears in the Markdown prose")
        elif url not in known_urls:
            out.critical.append(f"URL {url} does not appear in the specialist data")

    # 5. emails
    known_emails = {e.lower().rstrip(".") for e in _EMAIL.findall(data_text)}
    for email in {e.lower().rstrip(".") for e in _EMAIL.findall(md)}:
        if email not in known_emails:
            out.critical.append(f"email {email} does not appear in the specialist data")

    # 6. bold text: a catalog product that the specialist did not return is a mix-up
    allowed_names = [p["name"].lower() for p in result.data.get("products", [])]
    catalog = {n.lower() for n in catalog_names}
    for span in {s.strip().strip(":,.").lower() for s in _BOLD.findall(md)}:
        known = any(span == a or span in a or a in span for a in allowed_names)
        if known:
            continue
        if span in catalog:
            out.critical.append(f"mentions product '{span}' which is not in the specialist result")
        elif result.specialist in ("recommendation", "comparison"):
            out.non_critical.append(f"bold text '{span}' is not a returned product")

    # 7. out-of-stock wording (docs: never hide it, always say it)
    oos = [p["name"].lower() for p in result.data.get("products", []) if p["availability"] == "out_of_stock"]
    if any(name in low for name in oos) and OUT_OF_STOCK_PHRASE not in low:
        out.critical.append("an out-of-stock product is mentioned without 'Currently out of stock'")

    # 8. no customer-specific order/refund/delivery claims (support has no live data)
    if _ORDER_CLAIM.search(md):
        out.critical.append("makes a claim about the customer's own order/refund/delivery status")

    # 9. notes only
    if "trimmer_model_not_identified" in result.warnings and not re.search(
        r"model|variant|different|depends", low
    ):
        out.non_critical.append("trimmer variants are not acknowledged in the Markdown")
    return out
