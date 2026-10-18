"""scripts/try_query.py — see what Query Understanding extracts from a message.

Usage:
    python -m scripts.try_query "Suggest a razor for sensitive skin"
    python -m scripts.try_query "the second one" --history "user: compare A and B" "assistant: ..."
"""

import argparse
import asyncio
import sys

from app.core.logging import setup_logging
from app.graph.nodes.query_understanding import understand

setup_logging()


async def run(message: str, history_args: list[str]) -> None:
    history = []
    for item in history_args:
        role, _, content = item.partition(":")
        history.append({"role": role.strip().lower(), "content": content.strip()})
    result = await understand(message, history)
    print(result.model_dump_json(indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("message")
    parser.add_argument("--history", nargs="*", default=[], help='"user: ..." "assistant: ..."')
    args = parser.parse_args()
    try:
        asyncio.run(run(args.message, args.history))
    except Exception as exc:
        print(f"Failed: {type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
