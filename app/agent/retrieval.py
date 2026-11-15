"""app/agent/retrieval.py — hybrid product search (vector + keyword, fused) over an in-memory catalog.

Why hybrid: embeddings find "something fresh for office" but miss exact names
("Legend365"); keyword matching does the reverse. Each ranked list votes with
reciprocal-rank fusion (RRF), then Python applies hard filters (budget,
category), puts in-stock first, and drops duplicate listings of one product.

Why an in-memory catalog: the products table is small (~230 rows) and every DB
round trip to a hosted Postgres costs ~250 ms. The table stays the single source
of truth: the cache is reloaded from it every CACHE_SECONDS (and after a catalog
refresh, within that time). Only the vector lookup touches the DB per search.
"""

import logging
import re
import time
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.retrieval.search import search as vector_search

logger = logging.getLogger(__name__)

RRF_K = 60
CACHE_SECONDS = 120
STOPWORDS = {
    "the", "for", "and", "with", "any", "best", "good", "some", "want", "need", "show", "me", "my", "under",
    "below", "above", "around", "about", "this", "that", "please", "kind", "type", "men", "man", "mens",
}
_CACHE: dict[str, Any] = {"rows": {}, "until": 0.0}


async def catalog(conn: psycopg.AsyncConnection) -> dict[str, dict]:
    """id -> products row (with a lowercase search string under '_hay'). Reloaded every CACHE_SECONDS."""
    if _CACHE["until"] < time.monotonic():
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM products")
            rows = await cur.fetchall()
        for r in rows:
            tags = ((r.get("details") or {}).get("specifications") or {}).get("tags") or []
            r["_hay"] = f"{r['name']} {r['category']} {' '.join(tags) if isinstance(tags, list) else tags} {(r['description'] or '')[:500]}".lower()
        _CACHE["rows"] = {r["id"]: r for r in rows if not (r.get("details") or {}).get("delisted")}
        _CACHE["until"] = time.monotonic() + CACHE_SECONDS
        logger.info("Catalog cache loaded (%d products)", len(_CACHE["rows"]))
    return _CACHE["rows"]


def _tokens(query: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9+]+", query.lower()) if len(w) > 2 and w not in STOPWORDS][:6]


def keyword_ids(rows: dict[str, dict], query: str, limit: int = 25) -> list[str]:
    """Ids ranked by how many query words appear in name (x3) / category / tags / description."""
    toks = _tokens(query)
    scored = []
    for r in rows.values():
        name = r["name"].lower()
        s = sum((1 if t in r["_hay"] else 0) + (2 if t in name else 0) for t in toks)
        if s:
            scored.append((s, r["review_count"] or 0, r["id"]))
    scored.sort(reverse=True)
    return [i for _, _, i in scored[:limit]]


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def dedupe(items: list[dict]) -> list[dict]:
    """One card per product name: prefer the in-stock listing, then the cheaper one."""
    best: dict[str, dict] = {}
    for r in items:
        key = norm_name(r["name"])
        cur = best.get(key)
        if cur is None or (r["availability"] == "in_stock", -float(r["price"])) > (
                cur["availability"] == "in_stock", -float(cur["price"])):
            best[key] = r
    keep = {id(v) for v in best.values()}
    return [r for r in items if id(r) in keep]


async def hybrid_search(
    conn: psycopg.AsyncConnection,
    query: str,
    *,
    category: str | None = None,
    max_price: float | None = None,
    min_price: float | None = None,
    in_stock_only: bool = False,
    limit: int = 4,
) -> dict[str, Any]:
    """Returns {"products": [rows], "over_budget": [rows], "total_candidates": n}."""
    rows_by_id = await catalog(conn)
    query = (query or "").strip() or (category or "").strip()   # a model sometimes sends only a category
    fused: dict[str, float] = {}
    if query:
        try:
            for rank, h in enumerate(await vector_search(conn, query, "product", k=25)):
                fused[h.source_id] = fused.get(h.source_id, 0) + 1 / (RRF_K + rank)
        except Exception as exc:  # embeddings down: keyword search still works
            logger.warning("Vector search failed, keyword only: %s", type(exc).__name__)
        for rank, pid in enumerate(keyword_ids(rows_by_id, query)):
            fused[pid] = fused.get(pid, 0) + 1 / (RRF_K + rank)

    ordered = sorted(fused, key=fused.get, reverse=True)  # type: ignore[arg-type]
    rows = [rows_by_id[i] for i in ordered[:40] if i in rows_by_id]

    if category:
        c = category.lower()
        in_cat = [r for r in rows if c in r["category"].lower() or c in r["name"].lower()]
        if not in_cat:
            # The search words matched nothing inside the category: list its best-reviewed products instead.
            in_cat = sorted((r for r in rows_by_id.values() if c in r["category"].lower()),
                            key=lambda r: (r["availability"] != "in_stock", -(r["review_count"] or 0)))
        rows = in_cat
    if in_stock_only:
        rows = [r for r in rows if r["availability"] == "in_stock"]

    inside = [r for r in rows if (max_price is None or float(r["price"]) <= max_price)
              and (min_price is None or float(r["price"]) >= min_price)]
    over = [r for r in rows if max_price is not None and float(r["price"]) > max_price]

    inside = dedupe(inside)
    inside.sort(key=lambda r: r["availability"] != "in_stock")   # stable: in-stock first, fusion order kept
    return {
        "products": inside[:limit],
        "over_budget": sorted(dedupe(over), key=lambda r: float(r["price"]))[:2],
        "total_candidates": len(inside),
    }


async def deals(conn: psycopg.AsyncConnection, category: str | None, max_price: float | None, limit: int) -> list[dict]:
    """In-stock products with the biggest real discounts (price below original_price)."""
    rows = [r for r in (await catalog(conn)).values()
            if r["availability"] == "in_stock" and float(r["original_price"]) > float(r["price"]) > 0
            and (not category or category.lower() in r["category"].lower())
            and (max_price is None or float(r["price"]) <= max_price)]
    rows.sort(key=lambda r: ((float(r["original_price"]) - float(r["price"])) / float(r["original_price"]),
                             r["review_count"] or 0), reverse=True)
    return dedupe(rows)[:limit]


async def get_many(conn: psycopg.AsyncConnection, ids: list[str]) -> list[dict]:
    rows = await catalog(conn)
    return [rows[i] for i in ids if i in rows]


async def find_by_name(conn: psycopg.AsyncConnection, name: str) -> dict | None:
    rows = list((await catalog(conn)).values())
    n = norm_name(name)
    exact = [r for r in rows if norm_name(r["name"]) == n]
    pool = exact or [r for r in rows if n and n in norm_name(r["name"])]
    # "omniblade" must find the trimmer, not "OmniBlade Replacement Heads": accessories only win when asked for.
    accessory = re.compile(r"replacement|refill|cartridge|blades? pack|heads?\b|spare|attachment|oil\b|case\b", re.I)
    wants_accessory = bool(accessory.search(name))
    pool = sorted(pool, key=lambda r: (r["availability"] != "in_stock",
                                       bool(accessory.search(r["name"])) and not wants_accessory,
                                       -(r["review_count"] or 0) if r["category"] == "Trimmers" else 0,
                                       len(r["name"])))
    return pool[0] if pool else None


async def catalog_map(conn: psycopg.AsyncConnection) -> str:
    """'Category (n, ₹min-₹max)' lines, built from the live table so the prompt is never stale."""
    stats: dict[str, list[float]] = {}
    for r in (await catalog(conn)).values():
        if r["availability"] == "in_stock":
            stats.setdefault(r["category"], []).append(float(r["price"]))
    return "; ".join(f"{c} ({len(p)} in stock, ₹{min(p):g}-₹{max(p):g})"
                     for c, p in sorted(stats.items(), key=lambda kv: -len(kv[1])))
