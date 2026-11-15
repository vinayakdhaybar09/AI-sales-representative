"""evals/run_evals.py — replay every scenario through the real API and check the replies.

    python -m evals.run_evals                      # all scenarios
    python -m evals.run_evals --only hi_trimmer,vague_gift
    python -m evals.run_evals --tag adversarial
    python -m evals.run_evals --pace 8             # seconds between turns (free-tier token limits)

Needs the backend running on :8000. Writes evals/results/<timestamp>.json and a readable
evals/results/<timestamp>.md (summary, failures first, then full transcripts).
"""

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

import psycopg

from app.agent.prompt import detect_language
from app.core.config import get_settings
from evals.chat_cli import ask
from evals.scenarios import SCENARIOS

RESULTS = Path(__file__).parent / "results"
_ORDER_CLAIM = re.compile(r"your order (has|was|is) (already )?(shipped|packed|delivered|dispatched|on its way)|"
                          r"refund (has|was) (been )?(processed|issued|credited)", re.I)
_RAW_TOOL = re.compile(r"<tool_call|<function=|\[\[chips|tool_use|search_products\(")
_FALLBACKS = ("lost my train of thought", "assistant brain is busy", "Something went wrong")


def db_prices() -> dict[str, float]:
    with psycopg.connect(get_settings().database_url.get_secret_value()) as c:
        return {r[0]: float(r[1]) for r in c.execute("SELECT id, price FROM products").fetchall()}


def check_turn(body: dict, checks: dict, prices: dict[str, float]) -> list[str]:
    fails: list[str] = []
    if body.get("error"):
        return ["no response (error / timeout)"]
    reply = body["markdown"].replace("\u2019", "'").replace("\u2018", "'")   # curly quotes -> straight, so regexes match
    cards = body["product_tray"]
    words = len(reply.split())

    if not reply.strip():
        fails.append("empty reply")
    if body["type"] == "fallback" or any(f in reply for f in _FALLBACKS):
        fails.append("fallback / apology reply on an in-scope message")
    if _RAW_TOOL.search(reply):
        fails.append("raw tool or chips syntax leaked into the reply")
    if _ORDER_CLAIM.search(reply):
        fails.append("claims knowledge of the customer's order status")
    if words > checks.get("max_words", 140):
        fails.append(f"too long ({words} words)")
    if reply.count("?") > checks.get("max_q", 2):
        fails.append(f"asks {reply.count('?')} questions")
    for c in cards:
        if c["product_id"] in prices and abs(prices[c["product_id"]] - c["price"]) > 0.01:
            fails.append(f"card price mismatch for {c['name']}")

    lo, hi = checks.get("cards", (None, None)) if "cards" in checks else (None, None)
    n = len(cards) + (0 if not body.get("comparison_table") else len(body["comparison_table"]["products"]))
    if checks.get("no_cards") and n:
        fails.append(f"{n} cards shown, expected none")
    if lo is not None and not (lo <= n <= hi):
        fails.append(f"{n} cards shown, expected {lo}-{hi}")
    if "budget" in checks:
        over = [c["name"] for c in cards if c["price"] > checks["budget"]]
        if over:
            fails.append(f"over budget ₹{checks['budget']}: {', '.join(over)}")
    if checks.get("has") and not any(re.search(p, reply, re.I) for p in checks["has"]):
        fails.append(f"none of {checks['has']} found")
    for p in checks.get("all_has", []):
        if not re.search(p, reply, re.I):
            fails.append(f"missing /{p}/")
    for p in checks.get("not_has", []):
        if re.search(p, reply, re.I):
            fails.append(f"forbidden /{p}/ present")
    if checks.get("type_in") and body["type"] not in checks["type_in"]:
        fails.append(f"type {body['type']} not in {checks['type_in']}")
    if checks.get("form") and not body.get("form"):
        fails.append("expected the support form")
    if checks.get("table") and not body.get("comparison_table"):
        fails.append("expected a comparison table")
    if checks.get("bundle") and not body.get("bundle"):
        fails.append("expected a routine/bundle card")
    if checks.get("lang"):
        got = detect_language(reply)
        if checks["lang"] == "hinglish" and got not in ("hinglish", "hindi"):
            fails.append(f"reply is {got}, expected Hinglish")
        if checks["lang"] == "hindi" and got != "hindi":
            fails.append(f"reply is {got}, expected Hindi")
    return fails


def turn_log(conv: str) -> list[dict]:
    with psycopg.connect(get_settings().database_url.get_secret_value()) as c:
        rows = c.execute("SELECT model, tokens, jsonb_array_length(guard_issues), error, intent FROM turn_logs "
                         "WHERE conversation_id=%s ORDER BY id", (conv,)).fetchall()
    return [{"model": r[0], "tokens": r[1], "guard_issues": r[2], "error": r[3], "intent": r[4]} for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--tag")
    ap.add_argument("--pace", type=float, default=8.0)
    ap.add_argument("--resume", help="run id of an interrupted run: skip scenarios already saved")
    a = ap.parse_args()
    chosen = [s for s in SCENARIOS
              if (not a.only or s["id"] in a.only.split(",")) and (not a.tag or a.tag in s["tags"])]
    prices = db_prices()
    run_id = a.resume or datetime.now().strftime("%Y%m%d-%H%M%S")
    RESULTS.mkdir(exist_ok=True)
    partial = RESULTS / f"{run_id}.jsonl"          # one line per finished scenario, so a crash loses nothing
    results = [json.loads(l) for l in partial.read_text().splitlines()] if partial.exists() else []
    done_ids = {r["id"] for r in results}
    for si, sc in enumerate(chosen, 1):
        if sc["id"] in done_ids:
            continue
        conv = f"eval_{run_id}_{sc['id']}"
        print(f"[{si}/{len(chosen)}] {sc['id']}", flush=True)
        turns = []
        for message, checks in sc["turns"]:
            body = ask(conv, message, verbose=False)
            retried = False
            if body.get("error") or body.get("type") == "fallback":
                time.sleep(25)       # most likely a free-tier rate limit window: wait once and retry
                body, retried = ask(conv, message, verbose=False), True
            fails = check_turn(body, checks, prices)
            turns.append({"user": message, "reply": body.get("markdown", ""), "type": body.get("type"),
                          "cards": [(c["name"], c["price"], c["availability"]) for c in body.get("product_tray", [])],
                          "bundle_total": (body.get("bundle") or {}).get("total"),
                          "table": [p["name"] for p in (body.get("comparison_table") or {}).get("products", [])],
                          "chips": body.get("suggested_prompts", []), "first_token_s": body.get("_first_token"),
                          "total_s": body.get("_total"), "fails": fails, "retried": retried})
            print(f"    {'PASS' if not fails else 'FAIL'}  {message[:60]!r} {fails if fails else ''}", flush=True)
            time.sleep(a.pace)
        logs = turn_log(conv)
        results.append({"id": sc["id"], "tags": sc["tags"], "turns": turns, "log": logs})
        with partial.open("a") as f:
            f.write(json.dumps(results[-1], ensure_ascii=False) + "\n")

    write_report(run_id, results)


def write_report(run_id: str, results: list[dict]) -> None:
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{run_id}.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    all_turns = [t for r in results for t in r["turns"]]
    failed_turns = [t for t in all_turns if t["fails"]]
    scen_fail = [r for r in results if any(t["fails"] for t in r["turns"])]
    ft = sorted(t["first_token_s"] for t in all_turns if t["first_token_s"])
    tt = sorted(t["total_s"] for t in all_turns if t["total_s"])
    pct = lambda xs, p: xs[min(len(xs) - 1, int(len(xs) * p))] if xs else 0
    guard = sum((l["guard_issues"] or 0) > 0 for r in results for l in r["log"])
    models: dict[str, int] = {}
    for r in results:
        for l in r["log"]:
            models[l["model"] or "none"] = models.get(l["model"] or "none", 0) + 1
    out = [f"# Eval report {run_id}", "",
           f"- Scenarios: **{len(results)}** ({len(results) - len(scen_fail)} fully passing, {len(scen_fail)} with failures)",
           f"- Turns: **{len(all_turns)}** ({len(all_turns) - len(failed_turns)} passing, {len(failed_turns)} failing)",
           f"- First token p50 / p95: **{pct(ft, .5):.1f}s / {pct(ft, .95):.1f}s**; full reply p50 / p95: **{pct(tt, .5):.1f}s / {pct(tt, .95):.1f}s**",
           f"- Turns where the accuracy guard rewrote the reply: {guard}", f"- Answering models: {models}", "",
           "## Failures", ""]
    for r in scen_fail:
        out.append(f"### {r['id']}  ({' '.join(r['tags'])})")
        for t in r["turns"]:
            if t["fails"]:
                out += [f"- **{t['user']}**", f"  - {'; '.join(t['fails'])}", f"  - reply: {t['reply'][:260]!r}"]
        out.append("")
    out += ["## All transcripts", ""]
    for r in results:
        out.append(f"### {r['id']}")
        for t in r["turns"]:
            mark = "✅" if not t["fails"] else "❌"
            out += [f"{mark} **Customer:** {t['user']}", f"**Assistant ({t['type']}):** {t['reply']}"]
            if t["cards"]:
                out.append("Cards: " + "; ".join(f"{n} ₹{p:g}" + ("" if av == "in_stock" else " (OOS)") for n, p, av in t["cards"]))
            if t["bundle_total"]:
                out.append(f"Bundle total: ₹{t['bundle_total']:g}")
            if t["table"]:
                out.append("Comparison: " + " vs ".join(t["table"]))
            out.append("")
    (RESULTS / f"{run_id}.md").write_text("\n".join(out))
    print("\n".join(out[:12]))
    print(f"\nReport: evals/results/{run_id}.md")


if __name__ == "__main__":
    main()
