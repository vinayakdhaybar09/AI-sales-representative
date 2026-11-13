"""scripts/check_query_flow.py — test the query submission specialist and the form submit.

Usage:
    python -m scripts.check_query_flow          # offline: routing, specialist, form, validator (no LLM, no DB)
    python -m scripts.check_query_flow --db     # also POSTs /api/queries against the real database (test rows are deleted)
"""

import argparse
import asyncio
import sys
import uuid

from app.graph import builder, routers
from app.response.forms import check_form_reply, query_form_reply, support_query_form
from app.response.validator import validate
from app.schemas.query import Entities, QueryUnderstanding
from app.specialists import query_submission

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"   ({detail})" if detail and not ok else ""))


def offline() -> None:
    print("Routing and graph")
    q = QueryUnderstanding(intent="query_submission", scope="in_scope")
    check("intent routes to the specialist", routers.after_query_understanding({"query": q}) == "sufficiency")
    check("sufficiency leads to specialist_query_submission",
          routers.after_sufficiency({"query": q, "sufficient": True}) == "specialist_query_submission")
    check("node is in the graph", "specialist_query_submission" in builder.SPECIALISTS)
    builder.get_graph()

    print("Specialist")
    for message, expected in [
        ("i received defective product, i want my money back", "defective"),
        ("you sent me the wrong item", "wrong_item"),
        ("my order is delayed, order #BSC12345", "delivery"),
        ("I was charged twice", "payment"),
        ("I want to raise a query", ""),
    ]:
        out = asyncio.run(query_submission.run(QueryUnderstanding(intent="query_submission", scope="in_scope", entities=Entities()), message))
        got = out.data["prefill"].get("category", "")
        check(f"{message!r} -> {expected or 'no category'}", out.status == "success" and got == expected, got)
    out = asyncio.run(query_submission.run(QueryUnderstanding(intent="query_submission", scope="in_scope"), "order #BSC12345 is late"))
    check("order id is picked from the message", out.data["prefill"].get("order_id") == "#BSC12345")

    print("Form and validator")
    spec = support_query_form({"category": "defective"})
    keys = [f.key for f in spec.fields]
    check("form has unique keys", len(keys) == len(set(keys)))
    check("show_if only refers to real fields", all(k in keys for f in spec.fields for k in (f.show_if or {})))
    check("require_one_of refers to real fields", all(k in keys for g in spec.require_one_of for k in g))
    result = out
    reply = query_form_reply(result, "x")
    check("reply carries the form, no products", reply.type == "query_submission" and reply.form is not None and not reply.product_tray)
    check("validator accepts it", validate(reply, result, []).valid)
    bad = reply.model_copy(update={"form": None})
    check("validator rejects a reply without the form", not validate(bad, result, []).valid)
    check("check_form_reply is quiet for a good reply", check_form_reply(reply, result) == [])


def with_db() -> None:
    print("POST /api/queries (real database)")
    from fastapi.testclient import TestClient
    from app.main import app
    import psycopg
    from app.core.config import get_settings

    cid = f"check_{uuid.uuid4().hex[:10]}"
    key = uuid.uuid4().hex
    body = {
        "conversation_id": cid, "idempotency_key": key, "category": "defective",
        "description": "The trimmer does not switch on", "details": {"order_id": "#BSC1", "weird": "<b>kept as typed</b>"},
        "attachments": [{"name": "box.jpg", "size": 1234, "type": "image/jpeg"}],
    }
    with TestClient(app) as client:
        first = client.post("/api/queries", json=body)
        second = client.post("/api/queries", json=body)
        bad = client.post("/api/queries", json={**body, "idempotency_key": "x" * 12, "description": ""})
    check("first submit succeeds with a ref", first.status_code == 200 and first.json()["ref"].startswith("BSC-Q-"), first.text)
    check("same key returns the same ref", second.json().get("ref") == first.json().get("ref"))
    check("empty description is refused", bad.status_code == 422)
    with psycopg.connect(get_settings().database_url.get_secret_value(), autocommit=True) as conn:
        rows = conn.execute("SELECT ref, category, details, attachments_meta FROM support_queries WHERE conversation_id=%s", (cid,)).fetchall()
        check("exactly one row stored as typed", len(rows) == 1 and rows[0][2]["weird"] == "<b>kept as typed</b>" and rows[0][3][0]["name"] == "box.jpg", str(rows))
        conn.execute("DELETE FROM support_queries WHERE conversation_id=%s", (cid,))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", action="store_true")
    args = ap.parse_args()
    offline()
    if args.db:
        with_db()
    print(f"\n{'ALL PASSED' if not FAILED else f'{FAILED} FAILED'}")
    sys.exit(1 if FAILED else 0)
