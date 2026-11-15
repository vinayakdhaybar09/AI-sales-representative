"""app/agent/tools.py — the tools the salesperson agent can call.

Every tool returns compact JSON (the free models have tight per-minute token
limits) and records what it returned in the TurnContext. That record is what
makes the answer grounded: cards, comparison tables and bundle totals are built
in Python from rows the tools returned *this turn*, and the guard checks the
reply's prices/links against the same record.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import psycopg
from contextlib import asynccontextmanager

from app.agent import retrieval
from app.db.connection import get_pool
from app.response.forms import support_query_form
from app.response.text import clean_list, clean_text
from app.retrieval.search import search as vector_search
from app.schemas.chat import ProductCard

logger = logging.getLogger(__name__)

STORE_URL = "https://www.bombayshavingcompany.com"
MAX_SHOWN = 3
MAX_BUNDLE = 6
PROFILE_LIST_KEYS = {"concerns", "categories", "preferences", "dislikes"}
PROFILE_KEYS = {"for_whom", "skin_type", "hair_type", "budget_max", "occasion", "language", "name_hint"} | PROFILE_LIST_KEYS

def _fn(name: str, desc: str, props: dict, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, **({"required": required} if required else {})}}}


_S, _N, _IDS = {"type": "string"}, {"type": "number"}, {"type": "array", "items": {"type": "string"}}
TOOL_SCHEMAS: list[dict[str, Any]] = [
    _fn("search_products", "Search the live catalog (query in English). Returns up to 4 candidates.",
        {"query": _S, "category": _S, "max_price": _N, "min_price": _N, "in_stock_only": {"type": "boolean"}}, ["query"]),
    _fn("get_product", "Full facts for one product: features, how to use, ingredients, FAQs, variants.",
        {"product_id": _S, "name": _S}),
    _fn("compare_products", "Compare 2-3 products by name or id; the app draws the comparison table. Use whenever the customer asks to compare or 'X vs Y'.",
        {"names": _IDS, "product_ids": _IDS}),
    _fn("search_knowledge", "kind=policy: shipping, returns, refunds, cancellation, payment, warranty, tracking, contact. kind=guide: grooming how-tos.",
        {"query": _S, "kind": {"type": "string", "enum": ["policy", "guide"]}}, ["query", "kind"]),
    _fn("get_offers", "Biggest current discounts, in stock. No coupon codes exist.", {"category": _S, "max_price": _N}),
    _fn("build_routine", "Show a multi-step routine/combo with a computed total and add-all button.",
        {"title": _S, "steps": {"type": "array", "items": {"type": "object", "properties": {"label": _S, "product_id": _S}}}},
        ["title", "steps"]),
    _fn("handoff_to_human", "Show a prefilled support form for damaged/wrong/missing items, refunds, delivery problems, anger, or anything needing an order lookup.",
        {"category": {"type": "string", "enum": ["defective", "wrong_item", "missing_item", "delivery", "return_refund", "payment", "cancellation", "usage", "other"]},
         "summary": _S}, ["category", "summary"]),
    _fn("remember", "Save/correct customer facts: for_whom, skin_type, hair_type, concerns[], budget_max, categories[], preferences[], dislikes[], occasion, language. null removes.",
        {"updates": {"type": "object"}}, ["updates"]),
]


@dataclass
class TurnContext:
    """Everything the tools learned this turn. Built fresh per customer message."""
    profile: dict[str, Any]
    seen: dict[str, dict] = field(default_factory=dict)       # id -> products row returned by a tool
    shown_ids: list[str] = field(default_factory=list)
    compare_ids: list[str] = field(default_factory=list)
    bundle: dict | None = None
    form_prefill: dict | None = None
    profile_updates: dict[str, Any] = field(default_factory=dict)
    tool_log: list[dict] = field(default_factory=list)
    unmet: list[str] = field(default_factory=list)
    kinds_used: set[str] = field(default_factory=set)
    result_text: list[str] = field(default_factory=list)       # raw tool outputs, for the guard
    knowledge_urls: set[str] = field(default_factory=set)

    @asynccontextmanager
    async def db(self):
        """A pool connection per use, so tool calls can run concurrently (one connection cannot)."""
        async with get_pool().connection() as conn:
            yield conn


# ─── compact shapes ──────────────────────────────────────────────────────────

def _about(p: dict) -> str:
    details = p.get("details") or {}
    feats = clean_list(details.get("features"), 1, 110)
    return feats[0] if feats else clean_text(p.get("description"), 110)


_FACT_PATTERNS = [
    ("ipx", re.compile(r"\bIPX\s?(\d)\b", re.I), lambda m: f"IPX{m.group(1)} water rating"),
    ("waterproof", re.compile(r"\b(waterproof|water-proof|water resistant|washable|shower[- ]?proof)\b", re.I), lambda m: m.group(1).lower()),
    ("runtime", re.compile(r"(\d{2,3})\s*(?:min(?:ute)?s?)\s*(?:of\s*)?(?:run\s?time|runtime|usage|use|backup)", re.I), lambda m: f"{m.group(1)} min run time"),
    ("warranty", re.compile(r"(\d+)[- ]?(?:year|yr)s?\s*warranty", re.I), lambda m: f"{m.group(1)}-year warranty"),
    ("lengths", re.compile(r"(\d{1,3})\s*(?:length\s*)?(?:settings|lock-in|lengths)", re.I), lambda m: f"{m.group(1)} length settings"),
    ("cordless", re.compile(r"\b(cordless|rechargeable|usb[- ]?c|type[- ]?c)\b", re.I), lambda m: m.group(1).lower()),
]


def product_facts(p: dict) -> list[str]:
    """Hard facts found in the product's own text by regex (never inferred). Absence means 'unknown', not 'no'."""
    d = p.get("details") or {}
    info = d.get("detailed_information") if isinstance(d.get("detailed_information"), dict) else {}
    text = " ".join([p.get("name") or "", p.get("description") or "", " ".join(d.get("features") or []),
                     " ".join(info.get("key_features") or []), info.get("about_the_product") or ""])
    out = []
    for key, rx, fmt in _FACT_PATTERNS:
        m = rx.search(text)
        if m and (key != "waterproof" or "IPX" not in " ".join(out)):
            out.append(fmt(m))
    return out[:5]


def summarize(p: dict) -> dict[str, Any]:
    price, mrp = float(p["price"]), float(p.get("original_price") or 0)
    out: dict[str, Any] = {"id": p["id"], "name": p["name"], "category": p["category"], "price": price,
                           "stock": "in_stock" if p["availability"] == "in_stock" else "OUT_OF_STOCK"}
    if mrp > price:
        out["mrp"] = mrp
        out["off_pct"] = round((mrp - price) / mrp * 100)
    if int(p.get("review_count") or 0) > 0 and float(p.get("rating") or 0) > 0:
        out["rating"] = float(p["rating"])
        out["reviews"] = int(p["review_count"])
    about = _about(p)
    if about:
        out["about"] = about
    facts = product_facts(p)
    if facts:
        out["facts"] = facts
    return out


def _remember_rows(ctx: TurnContext, rows: list[dict]) -> None:
    for r in rows:
        ctx.seen[str(r["id"])] = r


def variant_id(p: dict) -> str | None:
    variants = ((p.get("details") or {}).get("specifications") or {}).get("variants") or []
    avail = [v for v in variants if v.get("available")]
    return (avail or variants or [{}])[0].get("id")


def cart_url(rows: list[dict]) -> str | None:
    pairs = [variant_id(r) for r in rows]
    if not rows or not all(pairs):
        return None
    return f"{STORE_URL}/cart/" + ",".join(f"{v}:1" for v in pairs)


# ─── tool implementations ────────────────────────────────────────────────────

async def _search_products(ctx: TurnContext, a: dict) -> dict:
    limit = 4
    async with ctx.db() as conn:
        res = await retrieval.hybrid_search(
            conn, str(a.get("query", "")), category=a.get("category"), max_price=a.get("max_price"),
            min_price=a.get("min_price"), in_stock_only=bool(a.get("in_stock_only")), limit=limit)
    _remember_rows(ctx, res["products"] + res["over_budget"])
    out: dict[str, Any] = {"results": [summarize(p) for p in res["products"]]}
    if not res["products"]:
        ctx.unmet.append(str(a.get("query", ""))[:120])
        out["note"] = ("No matching products for this search. If your query was empty or too narrow, search again with a "
                       "descriptive query before telling the customer anything is unavailable. Never invent products.")
    if res["over_budget"]:
        out["over_budget_options"] = [summarize(p) for p in res["over_budget"]]
    return out


async def _get_product(ctx: TurnContext, a: dict) -> dict:
    row = None
    if a.get("product_id"):
        async with ctx.db() as conn:
            row = next(iter(await retrieval.get_many(conn, [str(a["product_id"])])), None)
    if row is None and a.get("name"):
        async with ctx.db() as conn:
            row = await retrieval.find_by_name(conn, str(a["name"]))
    if row is None:
        return {"error": "product not found"}
    _remember_rows(ctx, [row])
    d, info = row.get("details") or {}, (row.get("details") or {}).get("detailed_information") or {}
    out = summarize(row)
    out["url"] = row["url"]
    out["description"] = clean_text(row.get("description"), 450)
    out["features"] = clean_list(d.get("features"), 6, 120)
    for key, n in (("how_to_use", 5), ("benefits", 4), ("key_features", 5)):
        vals = clean_list(info.get(key), n, 120) if isinstance(info, dict) else []
        if vals:
            out[key] = vals
    if isinstance(info, dict) and info.get("ingredients"):
        out["ingredients"] = clean_text(info["ingredients"], 300)
    faqs = [f for f in (info.get("faqs") or []) if isinstance(f, dict)][:3] if isinstance(info, dict) else []
    if faqs:
        out["faqs"] = [{"q": clean_text(f.get("question"), 120), "a": clean_text(f.get("answer"), 220)} for f in faqs]
    variants = ((d.get("specifications") or {}).get("variants") or [])
    if len(variants) > 1:
        out["variants"] = [{"title": v.get("title"), "price": v.get("price"), "available": v.get("available")}
                           for v in variants[:6]]
    out["missing"] = [k for k in ("ingredients", "how_to_use", "features") if not out.get(k)]
    return out


async def _compare_products(ctx: TurnContext, a: dict) -> dict:
    ids = [str(i) for i in (a.get("product_ids") or [])][:3]
    async with ctx.db() as conn:
        rows = await retrieval.get_many(conn, ids)
        for name in (a.get("names") or [])[:3]:
            found = await retrieval.find_by_name(conn, str(name))
            if found and found["id"] not in {r["id"] for r in rows}:
                rows.append(found)
        rows = rows[:3]
    if len(rows) < 2:
        return {"error": "could not find two products with those names; search first or ask which products"}
    _remember_rows(ctx, rows)
    ctx.compare_ids = [r["id"] for r in rows]
    out = []
    for r in rows:
        s = summarize(r)
        s["features"] = clean_list((r.get("details") or {}).get("features"), 5, 100)
        out.append(s)
    return {"products": out, "note": "The comparison table is shown by the app. Give a verdict for THIS customer; do not repeat the table."}


async def _search_knowledge(ctx: TurnContext, a: dict) -> dict:
    kind = "support" if a.get("kind") == "policy" else "blog"
    query = str(a.get("query", ""))
    async with ctx.db() as conn:
        hits = await vector_search(conn, query, kind, k=4 if kind == "support" else 3)
        pinned: list[str] = []
        if kind == "support" and re.search(r"return|exchange|replace|refund|damag|defect|wrong", query, re.I):
            # Pin the core returns policy: a side topic (e.g. refunds for courier-returned parcels) can
            # otherwise outrank it and make "returns" sound allowed.
            cur = await conn.execute(
                "SELECT content FROM embeddings WHERE source_type='support' AND metadata->>'topic' IN "
                "('Returns and Exchanges', 'Defective, Damaged, Expired, or Wrong Product') ORDER BY source_id")
            pinned = [r[0] for r in await cur.fetchall()]
    items = []
    for text in pinned:
        ctx.knowledge_urls.update(re.findall(r"https?://[^\s)\]>\"']+", text))
        items.append({"text": clean_text(text, 520)})
    for h in hits[: (3 if pinned else len(hits))]:
        text = clean_text(h.content, 520 if kind == "support" else 420)
        item: dict[str, Any] = {"text": text}
        if kind == "blog" and h.metadata.get("url"):
            item.update(title=h.metadata.get("title"), url=h.metadata["url"])
        ctx.knowledge_urls.update(re.findall(r"https?://[^\s)\]>\"']+", h.content))
        if h.metadata.get("url"):
            ctx.knowledge_urls.add(h.metadata["url"])
        items.append(item)
    out: dict[str, Any] = {"results": items}
    if kind == "support":
        out["note"] = ("Quote policy as written. If two results disagree (shipping fee, refund days, return window) "
                       "say so and point to care@bombayshavingcompany.com. You cannot see any customer's order.")
    if not items:
        ctx.unmet.append("knowledge: " + str(a.get("query", ""))[:100])
    return out


async def _get_offers(ctx: TurnContext, a: dict) -> dict:
    async with ctx.db() as conn:
        rows = await retrieval.deals(conn, a.get("category"), a.get("max_price"), 5)
    _remember_rows(ctx, rows)
    return {"deals": [summarize(r) for r in rows],
            "note": "Free shipping applies above the threshold stated in policy; check search_knowledge(policy) before quoting it. No coupon codes are published."}


async def _build_routine(ctx: TurnContext, a: dict) -> dict:
    steps = [s for s in (a.get("steps") or []) if isinstance(s, dict) and str(s.get("product_id")) in ctx.seen][:MAX_BUNDLE]
    if not steps:
        return {"error": "steps must use product ids returned by tools this turn"}
    rows = [ctx.seen[str(s["product_id"])] for s in steps]
    total = round(sum(float(r["price"]) for r in rows), 2)
    oos = [r["name"] for r in rows if r["availability"] != "in_stock"]
    ctx.bundle = {"title": clean_text(a.get("title"), 80) or "Your routine", "steps": [
        {"label": clean_text(s.get("label"), 40), "product_id": str(s["product_id"])} for s in steps],
        "total": total, "cart_url": cart_url(rows)}
    ctx.shown_ids = [str(s["product_id"]) for s in steps]
    return {"ok": True, "total": total, "out_of_stock": oos,
            "note": "Mention the total. Free shipping threshold: check policy before claiming it."}


async def _handoff(ctx: TurnContext, a: dict) -> dict:
    ctx.form_prefill = {"category": str(a.get("category") or "other"),
                        "description": clean_text(a.get("summary"), 500)}
    return {"ok": True, "note": "A prefilled support form is shown under your reply. Tell the customer what to keep ready: order ID, photos/video, invoice. Do not promise outcomes or timelines."}


async def _remember(ctx: TurnContext, a: dict) -> dict:
    updates = a.get("updates") if isinstance(a.get("updates"), dict) else {}
    clean = {k: v for k, v in updates.items() if k in PROFILE_KEYS}
    ctx.profile_updates.update(clean)
    return {"ok": True, "saved": list(clean)}


_IMPL = {"search_products": _search_products, "get_product": _get_product, "compare_products": _compare_products,
         "search_knowledge": _search_knowledge, "get_offers": _get_offers,
         "build_routine": _build_routine, "handoff_to_human": _handoff, "remember": _remember}

_KIND = {"search_products": "recommendation", "get_product": "product_question", "compare_products": "comparison",
         "get_offers": "deals", "build_routine": "routine", "handoff_to_human": "support_handoff"}


def apply_profile_updates(profile: dict, updates: dict) -> dict:
    """Merge in Python: lists accumulate, scalars overwrite, null removes (a correction)."""
    merged = dict(profile)
    for k, v in updates.items():
        if v is None:
            merged.pop(k, None)
        elif k in PROFILE_LIST_KEYS:
            cur = merged.get(k) or []
            add = v if isinstance(v, list) else [v]
            merged[k] = list(dict.fromkeys([*cur, *[str(x)[:60] for x in add]]))[:8]
        else:
            merged[k] = v if isinstance(v, (int, float)) else str(v)[:80]
    return merged


async def run_tool(ctx: TurnContext, name: str, raw_args: str | dict) -> str:
    """Execute one tool call; never raises. Returns the JSON string given back to the model."""
    t0 = time.monotonic()
    if isinstance(raw_args, dict):       # callers inside the app pass a dict; the model sends a JSON string
        args = raw_args
    else:
        try:
            args = json.loads(raw_args or "{}")
            if not isinstance(args, dict):
                args = {}
        except json.JSONDecodeError:
            args = {}
    impl = _IMPL.get(name)
    try:
        result = await impl(ctx, args) if impl else {"error": f"unknown tool {name}"}
    except Exception as exc:
        logger.warning("Tool %s failed: %s", name, type(exc).__name__)
        result = {"error": "tool failed; answer from what you know is safe or hand off honestly"}
    text = json.dumps(result, ensure_ascii=False)
    count = len(result.get("results") or result.get("products") or result.get("deals") or []) if isinstance(result, dict) else 0
    ctx.tool_log.append({"name": name, "args": args, "ms": round((time.monotonic() - t0) * 1000), "count": count})
    if name in _KIND:
        ctx.kinds_used.add(_KIND[name])
    if name == "search_knowledge":
        ctx.kinds_used.add("policy" if args.get("kind") == "policy" else "grooming_advice")
    ctx.result_text.append(text)
    return text


# ─── building the response parts (pure Python, from ctx only) ────────────────

def card(p: dict) -> ProductCard:
    from app.response.tray import card_extras
    return ProductCard(product_id=str(p["id"]), name=p["name"], price=float(p["price"]),
                       image_url=p.get("image_url") or "", product_url=p.get("url") or "",
                       availability=p["availability"], **card_extras(p))


def build_cards(ctx: TurnContext) -> list[ProductCard]:
    return [card(ctx.seen[i]) for i in ctx.shown_ids if i in ctx.seen]


def support_form(ctx: TurnContext):
    return support_query_form(ctx.form_prefill) if ctx.form_prefill is not None else None
