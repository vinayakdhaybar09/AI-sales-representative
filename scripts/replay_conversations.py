"""scripts/replay_conversations.py — replay the recorded customer conversations through the real graph.

Sends each conversation's user messages, in order, with a fresh conversation_id, and prints
per-turn results plus totals (fallbacks, model calls, time). Uses the real database and the
configured chat model, so it spends API calls: 22 conversations is about 200 turns.

Usage:
    python -m scripts.replay_conversations                    # all conversations
    python -m scripts.replay_conversations --only 3 5         # by position (1-based)
    python -m scripts.replay_conversations --pause 2          # seconds between turns (rate limits)
    python -m scripts.replay_conversations --out replay.json  # keep the full replies for reading
"""

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

from app.core.logging import setup_logging
from app.db.connection import close_pool, open_pool
from app.schemas.chat import ChatRequest
from app.services.chat_service import run_turn

setup_logging()
CASES = Path(__file__).with_name("replay_cases.json")


async def replay(selected: list[int] | None, pause: float, out_path: str | None) -> None:
    cases = json.loads(CASES.read_text())
    await open_pool()
    rows, totals = [], {"turns": 0, "fallback": 0, "error": 0, "llm_calls": 0, "seconds": 0.0, "fallback_convs": set()}
    try:
        for n, case in enumerate(cases, start=1):
            if selected and n not in selected:
                continue
            cid = f"replay_{n}_{uuid.uuid4().hex[:6]}"
            print(f"\n=== {n}. {case['title']} ({cid})")
            for i, message in enumerate(case["turns"]):
                envelope, stats, state = await run_turn(ChatRequest(message=message, conversation_id=cid))
                body = envelope.response
                kind = body.type if body else f"ERROR:{envelope.error.code}"
                totals["turns"] += 1
                totals["llm_calls"] += len(stats.llm_calls)
                totals["seconds"] += stats.total_seconds
                if kind == "fallback":
                    totals["fallback"] += 1
                    totals["fallback_convs"].add(n)
                if kind.startswith("ERROR"):
                    totals["error"] += 1
                issues = (state or {}).get("validation_issues") or []
                print(f"  [{i}] {kind:<14} llm={len(stats.llm_calls)} {stats.total_seconds:5.1f}s  {message[:70]!r}"
                      + (f"\n       issues: {'; '.join(issues)}" if issues else ""))
                rows.append({
                    "conv": n, "title": case["title"], "turn": i, "user": message, "type": kind,
                    "markdown": body.markdown if body else None,
                    "tray": [p.name for p in body.product_tray] if body else [],
                    "chips": body.suggested_prompts if body else [],
                    "llm_calls": [(label, round(s, 2)) for label, s in stats.llm_calls],
                    "embed_calls": stats.embed_calls, "seconds": round(stats.total_seconds, 2),
                    "issues": issues,
                })
                if pause:
                    await asyncio.sleep(pause)
    finally:
        await close_pool()

    t = totals
    print(f"\nTurns {t['turns']} | fallbacks {t['fallback']} in {len(t['fallback_convs'])} conversations "
          f"{sorted(t['fallback_convs'])} | errors {t['error']} | LLM calls {t['llm_calls']} "
          f"({t['llm_calls'] / max(t['turns'], 1):.2f}/turn) | avg {t['seconds'] / max(t['turns'], 1):.1f}s/turn")
    if out_path:
        Path(out_path).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        print(f"Full replies written to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", type=int, help="1-based positions of conversations to run")
    parser.add_argument("--pause", type=float, default=0.0, help="seconds to wait between turns")
    parser.add_argument("--out", help="write full replies to this JSON file")
    args = parser.parse_args()
    started = time.perf_counter()
    asyncio.run(replay(args.only, args.pause, args.out))
    print(f"Done in {time.perf_counter() - started:.0f}s")


if __name__ == "__main__":
    main()
