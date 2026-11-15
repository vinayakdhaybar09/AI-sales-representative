"""app/agent/guard.py — deterministic checks on the agent's reply (no LLM).

Same idea as app/response/validator.py, rebuilt for the tool-calling agent: the
reply may only contain prices, links and emails that tool results (or the
customer) contain, must not name catalog products the tools never returned,
and must not claim anything about a customer's order or make medical promises.
Returns a list of human-readable issues; empty means the reply passes.
"""

import itertools
import re

from app.agent.tools import TurnContext

CARE_EMAIL = "care@bombayshavingcompany.com"
_AMOUNT = re.compile(r"₹\s?(\d[\d,]*(?:\.\d+)?)|\bRs\.?\s?(\d[\d,]*(?:\.\d+)?)|\b(\d[\d,]{2,})\s?(?:rupees|rs)\b", re.I)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_URL = re.compile(r"https?://[^\s)\]>\"']+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ORDER_CLAIM = re.compile(
    r"\b(your order (?:has|was|is|will be)|order (?:has|was) (?:already )?(?:been )?(?:shipped|packed|delivered|dispatched|cancel+ed)|"
    r"refund (?:has|was|is) (?:been )?(?:processed|initiated|issued|credited)|i(?:'ve| have) (?:cancel+ed|refunded|placed|escalated))", re.I)
_MEDICAL = re.compile(
    r"\b(cures?|will cure|heals?|healing|treats? (?:eczema|psoriasis|infection|dermatitis|acne)|diagnos\w+|guarantee[ds]?|"
    r"100% (?:safe|effective|results)|permanent(?:ly)? (?:remov|grow)\w*|clinically proven)\b", re.I)


_LABEL_WORDS = ("trade", "why", "tip", "note", "pick", "best", "step", "total", "pro", "con", "morning", "night", "evening", "daily")


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _num(text: str) -> float:
    return float(text.replace(",", ""))


def _numbers(texts: list[str]) -> set[float]:
    out: set[float] = set()
    for t in texts:
        for m in _NUMBER.findall(t):
            try:
                out.add(_num(m))
            except ValueError:
                pass
    return out


def allowed_amounts(ctx: TurnContext, user_texts: list[str]) -> set[float]:
    base = _numbers(ctx.result_text) | _numbers(user_texts) | _numbers([str(ctx.profile.get("budget_max", ""))])
    base |= {0.0}
    small = sorted(n for n in base if 0 < n <= 20000)[:60]
    derived: set[float] = set()
    for a, b in itertools.combinations(small, 2):   # "₹60 more", "₹1,299 together"
        derived.add(round(abs(a - b), 2))
        derived.add(round(a + b, 2))
    return base | derived


def check(reply: str, ctx: TurnContext, user_texts: list[str], all_names: list[str]) -> list[str]:
    issues: list[str] = []
    allowed = allowed_amounts(ctx, user_texts)
    for m in _AMOUNT.finditer(reply):
        raw = next(g for g in m.groups() if g)
        try:
            amount = _num(raw)
        except ValueError:
            continue
        if amount not in allowed:
            issues.append(f"amount ₹{raw} is not in the tool data")

    urls_ok = {u.rstrip(".,") for u in ctx.knowledge_urls} | {r["url"] for r in ctx.seen.values() if r.get("url")}
    for u in _URL.findall(reply):
        if u.rstrip(".,") not in urls_ok:
            issues.append(f"link {u} is not from the tools")
    for e in _EMAIL.findall(reply):
        if e.lower() != CARE_EMAIL:
            issues.append(f"email {e} is not a known contact")

    # A catalog product named in bold must be one the tools returned this turn.
    seen_names = {r["name"].lower() for r in ctx.seen.values()}
    catalog = {n.lower() for n in all_names}
    for bold in re.findall(r"\*\*([^*\n]{3,70})\*\*", reply):
        b = bold.strip().lower().rstrip(".,:")
        if b in catalog and b not in seen_names:
            issues.append(f"product '{bold}' was not returned by any tool this turn")

    # A product LIST ("- **Name** – why") may only contain products the tools returned: this catches made-up
    # generic items like "BSC Face Wash" that no card can ever be built for.
    seen_compact = {_compact(r["name"]) for r in ctx.seen.values()}
    for lead in re.findall(r"^[ \t]*(?:[-*\u2022]|\d+[.)])[ \t]+\*\*([^*\n]{3,70})\*\*[ \t]*[\u2013\u2014-][ \t]", reply, re.M):
        c = _compact(lead)
        if lead.rstrip().endswith(":") or lead.lower().startswith(_LABEL_WORDS) or not c:
            continue
        if not any(c in sc or sc in c for sc in seen_compact):
            issues.append(f"'{lead.strip()}' is listed as a product but no tool returned it this turn")

    oos = {r["name"].lower() for r in ctx.seen.values() if r["availability"] != "in_stock"}
    for name in oos:
        if name in reply.lower() and "out of stock" not in reply.lower() and "unavailable" not in reply.lower():
            issues.append(f"'{name}' is out of stock but the reply does not say so")
            break
    if re.search(r"free (?:shipping|delivery)|shipping (?:is )?free", reply, re.I) and "policy" not in ctx.kinds_used:
        issues.append("free-shipping claim without checking the shipping policy (call search_knowledge kind=policy)")
    if _ORDER_CLAIM.search(reply):
        issues.append("claims something about the customer's order, which is not visible to you")
    if _MEDICAL.search(reply):
        issues.append("contains a medical claim or a guarantee")
    return issues
