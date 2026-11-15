"""GET /api/admin/stats — numbers for the owner's analytics view (demo: no auth, local only)."""

import json
import pathlib
import re
from collections import Counter

from fastapi import APIRouter, Query
from psycopg.rows import dict_row

from app.db.connection import get_pool

router = APIRouter(prefix="/api/admin", tags=["admin"])
STOP = set("the a an is are to for of and or in on it i me my you your can do does what which how this that with at be "
           "hai hain ka ki ke ko se me mein mujhe chahiye bhai batao kya aur tak ho hi ye woh please need want show".split())


async def _rows(cur, sql: str, params=()):
    await cur.execute(sql, params)
    return await cur.fetchall()


@router.get("/stats")
async def stats(days: int = Query(7, ge=1, le=90)) -> dict:
    since = f"now() - interval '{int(days)} days'"
    async with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        totals = (await _rows(cur, f"""
            SELECT count(*) turns, count(DISTINCT conversation_id) conversations,
                   count(*) FILTER (WHERE handoff) handoffs, count(*) FILTER (WHERE error IS NOT NULL) errors,
                   count(*) FILTER (WHERE jsonb_array_length(guard_issues) > 0) guard_flagged,
                   round(avg(first_token_ms)) avg_first_token_ms,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY total_ms) p50_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY total_ms) p95_ms
            FROM turn_logs WHERE created_at > {since}"""))[0]
        intents = await _rows(cur, f"SELECT intent, count(*) n FROM turn_logs WHERE created_at > {since} GROUP BY 1 ORDER BY n DESC")
        categories = await _rows(cur, f"""
            SELECT p.category, count(*) n FROM turn_logs t,
                 jsonb_array_elements_text(t.products_shown) pid JOIN products p ON p.id = pid
            WHERE t.created_at > {since} GROUP BY 1 ORDER BY n DESC LIMIT 10""")
        unmet = await _rows(cur, f"""
            SELECT q AS query, count(*) n FROM turn_logs t, jsonb_array_elements_text(t.unmet_queries) q
            WHERE t.created_at > {since} GROUP BY 1 ORDER BY n DESC, max(t.created_at) DESC LIMIT 15""")
        recommended = await _rows(cur, f"""
            SELECT p.id, p.name, p.price, count(*) shown FROM turn_logs t,
                 jsonb_array_elements_text(t.products_shown) pid JOIN products p ON p.id = pid
            WHERE t.created_at > {since} GROUP BY 1,2,3 ORDER BY shown DESC LIMIT 10""")
        events = await _rows(cur, f"""
            SELECT product_id, event_type, count(*) n FROM chat_events
            WHERE created_at > {since} AND product_id IS NOT NULL GROUP BY 1,2""")
        policy_q = await _rows(cur, f"""
            SELECT user_message, intent, created_at FROM turn_logs
            WHERE created_at > {since} AND intent IN ('policy','support_handoff') ORDER BY created_at DESC LIMIT 12""")
        recent = await _rows(cur, f"""
            SELECT conversation_id, user_message, left(reply, 220) reply, intent, total_ms, created_at
            FROM turn_logs WHERE created_at > {since} ORDER BY created_at DESC LIMIT 25""")
        msgs = [r["user_message"] for r in await _rows(cur, f"SELECT user_message FROM turn_logs WHERE created_at > {since} ORDER BY id DESC LIMIT 500")]
    by_product: dict[str, dict] = {}
    for e in events:
        by_product.setdefault(e["product_id"], {})[e["event_type"]] = e["n"]
    for r in recommended:
        r["price"] = float(r["price"])
        r.update({"clicks": by_product.get(r["id"], {}).get("product_click", 0),
                  "carts": by_product.get(r["id"], {}).get("add_to_cart", 0)})
    words = Counter(w for m in msgs for w in re.findall(r"[a-z]{3,}", m.lower()) if w not in STOP)
    report_dir = pathlib.Path("data/refresh_reports")
    latest = sorted(report_dir.glob("*.json"))[-1:] if report_dir.exists() else []
    refresh = json.loads(latest[0].read_text()) if latest else None
    if refresh:
        refresh = {k: (len(v) if isinstance(v, list) else v) for k, v in refresh.items()} | {"file": latest[0].name}
    for t in (totals, ):
        for k in ("p50_ms", "p95_ms", "avg_first_token_ms"):
            t[k] = int(t[k]) if t[k] is not None else None
    return {"days": days, "totals": totals, "intents": intents, "categories_shown": categories, "unmet_queries": unmet,
            "most_recommended": recommended, "top_terms": words.most_common(15), "policy_and_support": policy_q,
            "recent": recent, "catalog_refresh": refresh}
