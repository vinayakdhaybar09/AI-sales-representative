"""scripts/check_persistence.py — conversations survive restarts and expire when idle.

Usage:  python -m scripts.check_persistence
Needs DATABASE_URL and the conversations table (python -m scripts.apply_schema).
"""

import asyncio
import json
import subprocess
import sys

from app.core.config import get_settings
from app.db.connection import close_pool, get_pool, open_pool
from app.graph import conversation_store

CID = "check_persistence_1"
PENDING = {"original_query": "Suggest a trimmer", "intent": "recommendation",
           "missing_field": "use_case", "question": "Beard, body or both?", "attempt_count": 1}
HISTORY = [{"role": "user", "content": "Suggest a trimmer"}, {"role": "assistant", "content": "Beard, body or both?"}]
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")


async def main() -> None:
    ttl = get_settings().conversation_ttl_minutes
    await open_pool()
    try:
        async with get_pool().connection() as conn:
            await conn.execute("DELETE FROM conversations WHERE conversation_id LIKE 'check_persistence_%'")

        await conversation_store.save(CID, HISTORY, ["p1", "p2"], PENDING)
        # A brand-new Python process stands in for "the server restarted".
        out = subprocess.run(
            [sys.executable, "-c",
             "import asyncio, json\n"
             "from app.db.connection import open_pool, close_pool\n"
             "from app.graph import conversation_store as s\n"
             "async def m():\n"
             "    await open_pool(); print(json.dumps(await s.load('check_persistence_1'))); await close_pool()\n"
             "asyncio.run(m())"],
            capture_output=True, text=True,
        )
        loaded = json.loads(out.stdout.strip().splitlines()[-1])
        check("history, product ids and pending_clarification survive a new process",
              loaded == {"history": HISTORY, "previous_product_ids": ["p1", "p2"], "pending_clarification": PENDING})

        await conversation_store.save(CID, HISTORY, [], None)
        check("pending_clarification can be cleared", (await conversation_store.load(CID))["pending_clarification"] is None)

        async with get_pool().connection() as conn:
            await conn.execute(
                "UPDATE conversations SET updated_at = now() - interval '1 minute' * %s WHERE conversation_id = %s",
                (ttl + 5, CID))
        expired = await conversation_store.load(CID)
        check(f"idle > {ttl:g} min -> treated as a new conversation",
              expired == {"history": [], "previous_product_ids": [], "pending_clarification": None})
        async with get_pool().connection() as conn:
            row = await (await conn.execute("SELECT 1 FROM conversations WHERE conversation_id = %s", (CID,))).fetchone()
        check("expired row was deleted", row is None)

        async with get_pool().connection() as conn:
            for i in (2, 3):
                await conn.execute(
                    "INSERT INTO conversations (conversation_id, updated_at) VALUES (%s, now() - interval '1 minute' * %s)",
                    (f"check_persistence_{i}", ttl + 10))
        await conversation_store.save("check_persistence_4", HISTORY, [], None)
        async with get_pool().connection() as conn:
            left = await (await conn.execute(
                "SELECT conversation_id FROM conversations WHERE conversation_id LIKE 'check_persistence_%' ORDER BY 1")).fetchall()
        check("saving purges other expired conversations", [r[0] for r in left] == ["check_persistence_4"])

        async with get_pool().connection() as conn:
            await conn.execute("DELETE FROM conversations WHERE conversation_id LIKE 'check_persistence_%'")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
    print("\nRESULT:", "ALL PASS" if all(ok for _, ok in results) else "FAILURES")
    sys.exit(0 if all(ok for _, ok in results) else 1)
