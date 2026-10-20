"""app/llm/retry.py — retry policy for chat-model calls.

langchain-mistralai retries network errors (max_retries) but not HTTP errors,
and the free tier rate-limits often. This helper retries HTTP 429 and 5xx with
exponential backoff + jitter, honouring `Retry-After` when Mistral sends it.
Timeouts and connection errors are deliberately NOT retried here: the client
already retries them, and stacking both would multiply the waiting time.
"""

import asyncio
import logging
import random
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 3
BASE_WAIT_SECONDS = 1.5
MAX_WAIT_SECONDS = 15.0


def _wait_seconds(exc: httpx.HTTPStatusError, attempt: int) -> float:
    """Retry-After if the server gave one, else exponential backoff; always capped."""
    header = exc.response.headers.get("retry-after", "")
    try:
        base = float(header)
    except ValueError:
        base = BASE_WAIT_SECONDS * (2 ** attempt)
    return min(MAX_WAIT_SECONDS, base) * random.uniform(0.8, 1.2)


async def ainvoke_with_retry(runnable: Any, payload: Any) -> Any:
    """`await runnable.ainvoke(payload)`, retrying HTTP 429/5xx a few times."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await runnable.ainvoke(payload)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status not in RETRY_STATUSES or attempt == MAX_RETRIES:
                raise
            wait = _wait_seconds(exc, attempt)
            logger.warning("Mistral HTTP %d; retry %d/%d in %.1fs", status, attempt + 1, MAX_RETRIES, wait)
            await asyncio.sleep(wait)
