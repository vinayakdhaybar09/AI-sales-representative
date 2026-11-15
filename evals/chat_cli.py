"""Tiny dev client for the streaming chat endpoint.

    python -m evals.chat_cli <conversation_id> "message"
Prints status events with timings, then the final reply, cards, chips and extras.
"""
import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"


def ask(conv: str, message: str, verbose: bool = True) -> dict:
    t0, first, final = time.time(), None, None
    with httpx.stream("POST", f"{BASE}/api/chat/stream", json={"message": message, "conversation_id": conv}, timeout=120) as r:
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            e = json.loads(line[5:])
            if e["event"] == "token" and first is None:
                first = time.time() - t0
            elif e["event"] == "final":
                final = e["body"]
            elif e["event"] in ("status", "revise", "error", "reset") and verbose:
                print(f"  [{e['event']} {time.time()-t0:.1f}s] {e.get('text') or e.get('message') or ''}"[:140])
    total = time.time() - t0
    if final is None:
        return {"error": True, "total": total}
    final["_first_token"], final["_total"] = first, total
    return final


if __name__ == "__main__":
    b = ask(sys.argv[1], sys.argv[2])
    if b.get("error"):
        print("ERROR")
        sys.exit(1)
    print(f"\n[{b['type']}] first token {b['_first_token'] and round(b['_first_token'],1)}s, total {b['_total']:.1f}s")
    print(b["markdown"])
    for c in b["product_tray"]:
        print(f"  CARD {c['name']} ₹{c['price']:g} {c['availability']} rating={c.get('rating')}")
    if b.get("bundle"):
        print("  BUNDLE", b["bundle"]["title"], "total", b["bundle"]["total"], b["bundle"]["cart_url"])
    if b.get("comparison_table"):
        print("  TABLE", [p["name"] for p in b["comparison_table"]["products"]])
    if b.get("form"):
        print("  FORM prefill", b["form"]["prefill"])
    print("  CHIPS", b["suggested_prompts"])
