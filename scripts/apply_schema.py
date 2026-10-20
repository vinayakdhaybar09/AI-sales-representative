"""scripts/apply_schema.py — create/update tables from app/db/schema.sql.

Usage:  python -m scripts.apply_schema
Every statement is idempotent, so running it again is safe.
"""

import asyncio
import pathlib
import sys

import psycopg

from app.core.config import get_settings

SCHEMA = pathlib.Path("app/db/schema.sql")


async def run() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL is not set. Add it to .env and retry.")
        return 1
    async with await psycopg.AsyncConnection.connect(
        settings.database_url.get_secret_value(), autocommit=True
    ) as conn:
        await conn.execute(SCHEMA.read_text(encoding="utf-8"))
        cur = await conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        print("Schema applied. Tables:", [row[0] for row in await cur.fetchall()])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
