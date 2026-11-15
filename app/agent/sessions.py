"""app/agent/sessions.py — SQL-only persistence for chat sessions, turn logs and UI events."""

import json
from typing import Any

import psycopg
from psycopg.rows import dict_row


async def load_session(conn: psycopg.AsyncConnection, conversation_id: str, ttl_minutes: float) -> dict[str, Any]:
    """Messages, profile and shown ids; an idle session older than the TTL counts as new."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT messages, profile, shown_ids FROM chat_sessions "
            "WHERE conversation_id = %s AND updated_at > now() - (%s * interval '1 minute')",
            (conversation_id, ttl_minutes),
        )
        row = await cur.fetchone()
    return row or {"messages": [], "profile": {}, "shown_ids": []}


async def save_session(conn: psycopg.AsyncConnection, conversation_id: str, messages: list, profile: dict, shown_ids: list) -> None:
    await conn.execute(
        """
        INSERT INTO chat_sessions (conversation_id, messages, profile, shown_ids, updated_at)
        VALUES (%s, %s::jsonb, %s::jsonb, %s::jsonb, now())
        ON CONFLICT (conversation_id) DO UPDATE SET messages = EXCLUDED.messages,
            profile = EXCLUDED.profile, shown_ids = EXCLUDED.shown_ids, updated_at = now()
        """,
        (conversation_id, json.dumps(messages), json.dumps(profile), json.dumps(shown_ids)),
    )


async def log_turn(conn: psycopg.AsyncConnection, **f: Any) -> None:
    await conn.execute(
        """
        INSERT INTO turn_logs (conversation_id, user_message, reply, intent, tools, products_shown, unmet_queries,
                               guard_issues, handoff, model, first_token_ms, total_ms, tokens, error)
        VALUES (%(conversation_id)s, %(user_message)s, %(reply)s, %(intent)s, %(tools)s::jsonb, %(products_shown)s::jsonb,
                %(unmet_queries)s::jsonb, %(guard_issues)s::jsonb, %(handoff)s, %(model)s, %(first_token_ms)s,
                %(total_ms)s, %(tokens)s, %(error)s)
        """,
        {**f, "tools": json.dumps(f.get("tools", []), default=str),
         "products_shown": json.dumps(f.get("products_shown", [])),
         "unmet_queries": json.dumps(f.get("unmet_queries", [])),
         "guard_issues": json.dumps(f.get("guard_issues", []))},
    )


async def log_event(conn: psycopg.AsyncConnection, conversation_id: str, event_type: str, product_id: str | None, meta: dict) -> None:
    await conn.execute(
        "INSERT INTO chat_events (conversation_id, event_type, product_id, meta) VALUES (%s, %s, %s, %s::jsonb)",
        (conversation_id, event_type, product_id, json.dumps(meta)),
    )
