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
import time
from typing import Any

import httpx

from app.core import turn_stats

logger = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 3
BASE_WAIT_SECONDS = 1.5
MAX_WAIT_SECONDS = 15.0


def _http_error(exc: BaseException) -> tuple[int, str] | None:
    """(status, Retry-After header) when `exc` or its cause is an HTTP error from Mistral (httpx)
    or Gemini (google-genai, whose errors carry the status in `.code`); otherwise None."""
    while exc is not None:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code, exc.response.headers.get("retry-after", "")
        if type(exc).__module__.startswith("google.genai") and isinstance(getattr(exc, "code", None), int):
            return exc.code, ""
        exc = exc.__cause__
    return None


def _wait_seconds(header: str, attempt: int) -> float:
    """Retry-After if the server gave one, else exponential backoff; always capped."""
    try:
        base = float(header)
    except ValueError:
        base = BASE_WAIT_SECONDS * (2 ** attempt)
    return min(MAX_WAIT_SECONDS, base) * random.uniform(0.8, 1.2)


async def ainvoke_with_retry(runnable: Any, payload: Any, label: str = "llm") -> Any:
    """`await runnable.ainvoke(payload)`, retrying HTTP 429/5xx a few times.

    Every attempt is counted in the turn stats under `label` (log only).
    """
    for attempt in range(MAX_RETRIES + 1):
        began = time.perf_counter()
        try:
            return await runnable.ainvoke(payload)
        except Exception as exc:
            error = _http_error(exc)
            if error is None or error[0] not in RETRY_STATUSES or attempt == MAX_RETRIES:
                raise
            status, retry_after = error
            wait = _wait_seconds(retry_after, attempt)
            logger.warning("LLM HTTP %d; retry %d/%d in %.1fs", status, attempt + 1, MAX_RETRIES, wait)
            await asyncio.sleep(wait)
        finally:
            stats = turn_stats.current()
            if stats is not None:
                stats.add_llm(label, time.perf_counter() - began)
