"""scripts/try_query.py — see what Query Understanding extracts from a message.

Usage:
    python -m scripts.try_query "Suggest a razor for sensitive skin"
    python -m scripts.try_query "the second one" --history "user: compare A and B" "assistant: ..."
    python -m scripts.try_query "difference between the cream and the spray" --shown "Hair Removal Cream:Hair removal" "Hair Removal Spray:Hair removal"
"""

import argparse
import asyncio
import sys

from app.core.logging import setup_logging
from app.graph.nodes.query_understanding import understand

setup_logging()


async def run(message: str, history_args: list[str], shown_args: list[str]) -> None:
    history = []
    for item in history_args:
        role, _, content = item.partition(":")
        history.append({"role": role.strip().lower(), "content": content.strip()})
    shown = [{"name": n.partition(":")[0], "category": n.partition(":")[2] or None} for n in shown_args]
    result = await understand(message, history, shown_products=shown or None)
    print(result.model_dump_json(indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("message")
    parser.add_argument("--history", nargs="*", default=[], help='"user: ..." "assistant: ..."')
    parser.add_argument("--shown", nargs="*", default=[], help='products shown last, "Name:Category" ...')
    args = parser.parse_args()
    try:
        asyncio.run(run(args.message, args.history, args.shown))
    except Exception as exc:
        print(f"Failed: {type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
