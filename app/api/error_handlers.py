"""app/api/error_handlers.py — every /api/* failure becomes the standard envelope.

Only /api/* is converted; other routes (/health, /dev/*) keep FastAPI's defaults.
Expected failures are mapped inside handle_chat; these handlers cover what
happens before it runs (bad input) and genuine surprises.
"""

import json
import logging

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import INTERNAL_ERROR, INVALID_REQUEST, STATUS_BY_CODE, AppError, classify
from app.response.envelope import error_envelope

logger = logging.getLogger(__name__)


def _conversation_id_from(body: object) -> str:
    """Echo the conversation_id only when the body carried a usable one."""
    if isinstance(body, (bytes, str)):
        try:
            body = json.loads(body)
        except ValueError:
            return ""
    if isinstance(body, dict) and isinstance(body.get("conversation_id"), str):
        return body["conversation_id"][:100]
    return ""


def _validation_message(exc: RequestValidationError) -> str:
    """'field: problem' for each error; never echoes the submitted values."""
    parts = []
    for err in exc.errors()[:3]:
        loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body") or "request"
        parts.append(f"{loc}: {err.get('msg', 'invalid value')}")
    return "Invalid request. " + "; ".join(parts)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError):
        if not request.url.path.startswith("/api/"):
            return await request_validation_exception_handler(request, exc)
        envelope = error_envelope(_conversation_id_from(exc.body), INVALID_REQUEST, _validation_message(exc))
        return JSONResponse(status_code=422, content=envelope.model_dump(mode="json"))

    @app.exception_handler(AppError)
    async def on_app_error(request: Request, exc: AppError):
        """Expected, client-safe failures (e.g. an unknown product id): the standard envelope, no error log."""
        envelope = error_envelope("", exc.code, exc.message)
        return JSONResponse(status_code=exc.status, content=envelope.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def on_unhandled_error(request: Request, exc: Exception):
        logger.error("Unhandled error on %s", request.url.path, exc_info=exc)
        if not request.url.path.startswith("/api/"):
            return JSONResponse(status_code=500, content={"detail": "Internal server error"})
        err = classify(exc)
        envelope = error_envelope("", err.code or INTERNAL_ERROR, err.message)
        return JSONResponse(status_code=STATUS_BY_CODE.get(err.code, 500), content=envelope.model_dump(mode="json"))
