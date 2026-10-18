"""scripts/try_specialist.py — print specialist output for sample queries.

Usage:
    python -m scripts.try_specialist                 # all built-in samples
    python -m scripts.try_specialist recommendation  # one specialist
Runs the real Query Understanding model, then the specialist, and prints a
compact view (use --full for the complete JSON).
"""

import argparse
import asyncio
import json

import psycopg
from pgvector.psycopg import register_vector_async

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.graph.nodes.query_understanding import understand
from app.specialists import comparison, knowledge, recommendation, support

setup_logging()

SAMPLES = {
    "recommendation": [
        "Suggest a razor for sensitive skin",
        "Suggest a body wash under 300",
        "Best beard oil for dry beard",
        "Suggest a trimmer for beard grooming under 2000",
        "Suggest a razor under 10 rupees",
    ],
    "comparison": [
        "Compare Sensi Smart 3 Razor with Sensitive Shaving Foam",
        "Compare All Rounder 2-in-1 Trimmer with 12-in-1 Legend365 Trimmer",
        "Compare Sensi Smrt 3 Razer and Legend365",
        "Compare Hair Comb White with Unicorn Wand",
    ],
    "knowledge": [
        "How do I fix a patchy beard?",
        "How to use beard oil?",
        "Why does my dandruff treatment not work?",
        "What is the capital of France?",
    ],
    "support": [
        "Where is my order?",
        "What is the run time of the trimmer?",
        "What are the shipping charges?",
        "Can I return a product?",
        "Is the trimmer waterproof?",
    ],
}
RUNNERS = {
    "recommendation": lambda c, q, t: recommendation.run(c, q, t),
    "comparison": lambda c, q, t: comparison.run(c, q, []),
    "knowledge": lambda c, q, t: knowledge.run(c, q, t),
    "support": lambda c, q, t: support.run(c, q, t),
}


def compact(out) -> dict:
    d = out.data
    view = {"status": out.status, "warnings": out.warnings}
    if "products" in d:
        view["products"] = [f"{p['name']} | Rs {p['price']} | {p['availability']}" for p in d["products"]]
    if "unresolved" in d:
        view["unresolved"] = d["unresolved"]
    if "chunks" in d:
        view["chunks"] = [f"{c['title']} / {c['heading']} ({c['score']})" for c in d["chunks"]]
    if "items" in d:
        view["items"] = [f"{i['source_id']} {i['content'].splitlines()[0][:60]}" for i in d["items"]]
        view["contact_info"] = d["contact_info"]
    return view


async def run(only: str | None, full: bool) -> None:
    async with await psycopg.AsyncConnection.connect(
        get_settings().database_url.get_secret_value(), autocommit=True
    ) as conn:
        await register_vector_async(conn)
        for name, queries in SAMPLES.items():
            if only and name != only:
                continue
            for text in queries:
                query = await understand(text, [])
                # The graph picks the specialist from the intent; here we force it.
                out = await RUNNERS[name](conn, query, text)
                print(f"\n== [{name}] {text}")
                print(json.dumps(out.model_dump(mode="json") if full else compact(out),
                                 indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("specialist", nargs="?", choices=list(SAMPLES))
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.specialist, args.full))


if __name__ == "__main__":
    main()
