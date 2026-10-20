"""app/core/errors.py — one place that turns any failure into a client-safe error.

`classify(exc)` returns an AppError with a stable `code`, a message that is safe
to show a user (no stack traces, no keys, no internals) and the HTTP status.
"""

import logging
from dataclasses import dataclass

import httpx
import psycopg
from psycopg_pool import PoolTimeout

from app.db.connection import DatabaseNotReadyError
from app.llm.models import MissingApiKeyError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppError(Exception):
    code: str
    message: str
    status: int


INVALID_REQUEST = "invalid_request"
RATE_LIMITED = "rate_limited"
UPSTREAM_TIMEOUT = "upstream_timeout"
UPSTREAM_UNAVAILABLE = "upstream_unavailable"
SERVICE_UNAVAILABLE = "service_unavailable"
INTERNAL_ERROR = "internal_error"

_ERRORS = {
    RATE_LIMITED: AppError(RATE_LIMITED, "The assistant is very busy right now. Please try again in a moment.", 429),
    UPSTREAM_TIMEOUT: AppError(UPSTREAM_TIMEOUT, "The assistant took too long to respond. Please try again.", 504),
    UPSTREAM_UNAVAILABLE: AppError(UPSTREAM_UNAVAILABLE, "The AI service is temporarily unavailable. Please try again shortly.", 503),
    SERVICE_UNAVAILABLE: AppError(SERVICE_UNAVAILABLE, "The service is not available right now. Please try again later.", 503),
    INTERNAL_ERROR: AppError(INTERNAL_ERROR, "Something went wrong while processing your message. Please try again.", 500),
}

STATUS_BY_CODE = {code: err.status for code, err in _ERRORS.items()} | {INVALID_REQUEST: 422}


def invalid_request(message: str) -> AppError:
    return AppError(INVALID_REQUEST, message, 422)


def classify(exc: BaseException) -> AppError:
    """Map an exception to a client-safe AppError (unknown -> internal_error)."""
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return _ERRORS[UPSTREAM_TIMEOUT]
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return _ERRORS[RATE_LIMITED]
        if status in (401, 403):   # bad or exhausted key: an operator problem, not the user's
            return _ERRORS[SERVICE_UNAVAILABLE]
        return _ERRORS[UPSTREAM_UNAVAILABLE]
    if isinstance(exc, httpx.RequestError):
        return _ERRORS[UPSTREAM_UNAVAILABLE]
    if isinstance(exc, (MissingApiKeyError, DatabaseNotReadyError, PoolTimeout, psycopg.Error)):
        return _ERRORS[SERVICE_UNAVAILABLE]
    return _ERRORS[INTERNAL_ERROR]
