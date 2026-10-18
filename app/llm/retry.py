"""app/llm/retry.py — minimal 429 retry for chat calls.

langchain-mistralai retries network errors but not HTTP 429, and the free tier
rate-limits often. This is the smallest useful guard; M5 adds the full policy.
"""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RETRIES = 2
BASE_WAIT_SECONDS = 3.0


async def ainvoke_with_429_retry(runnable: Any, payload: Any) -> Any:
    """`await runnable.ainvoke(payload)`, waiting and retrying on HTTP 429 only."""
    for attempt in range(RETRIES + 1):
        try:
            return await runnable.ainvoke(payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 429 or attempt == RETRIES:
                raise
            wait = BASE_WAIT_SECONDS * (attempt + 1)
            logger.warning("Mistral rate limit (429); retrying in %.0fs", wait)
            await asyncio.sleep(wait)
