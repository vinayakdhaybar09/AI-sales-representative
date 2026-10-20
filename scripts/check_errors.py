"""scripts/check_errors.py — every failure is a clean error envelope, never a stack trace.

Usage:  python -m scripts.check_errors
Runs the real FastAPI app in-process; the graph is replaced by fakes that raise
specific errors. Needs DATABASE_URL (the app opens its pool at startup).
"""

import asyncio
import sys

import httpx
import psycopg
from fastapi.testclient import TestClient

import app.services.chat_service as chat_service
from app.core.config import get_settings
from app.llm.models import MissingApiKeyError
from app.main import app

results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" -> {detail}"))


def is_envelope(body: dict) -> bool:
    return set(body) == {"success", "conversation_id", "response", "error"} and body["success"] is False


class FailingGraph:
    def __init__(self, exc: BaseException | None = None, delay: float = 0):
        self.exc, self.delay = exc, delay

    async def ainvoke(self, _state):
        await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc


def status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://api.mistral.ai/v1/chat/completions")
    return httpx.HTTPStatusError("boom", request=req, response=httpx.Response(code, request=req))


GOOD = {"message": "hello", "conversation_id": "err_1"}


class FlakyModel:
    """Fails with the given HTTP statuses, then answers."""

    def __init__(self, statuses: list[int], retry_after: str | None = None):
        self.statuses, self.calls, self.retry_after = list(statuses), 0, retry_after

    async def ainvoke(self, _payload):
        self.calls += 1
        if self.statuses:
            code = self.statuses.pop(0)
            req = httpx.Request("POST", "https://api.mistral.ai/v1/chat/completions")
            headers = {"retry-after": self.retry_after} if self.retry_after else {}
            raise httpx.HTTPStatusError("x", request=req, response=httpx.Response(code, request=req, headers=headers))
        return "ok"


def check_retry_policy() -> None:
    import app.llm.retry as retry

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    real_sleep, retry.asyncio.sleep = retry.asyncio.sleep, fake_sleep
    try:
        m = FlakyModel([429, 503])
        out = asyncio.run(retry.ainvoke_with_retry(m, "p"))
        check("retries 429 then 503, then succeeds", out == "ok" and m.calls == 3 and len(sleeps) == 2, f"calls={m.calls}")
        check("backoff grows between retries", sleeps[1] > sleeps[0], str(sleeps))
        m = FlakyModel([400])
        try:
            asyncio.run(retry.ainvoke_with_retry(m, "p")); raised = False
        except httpx.HTTPStatusError:
            raised = True
        check("400 is not retried", raised and m.calls == 1, f"calls={m.calls}")
        m = FlakyModel([429] * 10)
        try:
            asyncio.run(retry.ainvoke_with_retry(m, "p")); raised = False
        except httpx.HTTPStatusError:
            raised = True
        check("gives up after the retry limit (4 calls total)", raised and m.calls == retry.MAX_RETRIES + 1, f"calls={m.calls}")
        sleeps.clear()
        m = FlakyModel([429], retry_after="7")
        asyncio.run(retry.ainvoke_with_retry(m, "p"))
        check("honours Retry-After", 5.5 <= sleeps[0] <= 8.5, str(sleeps))
    finally:
        retry.asyncio.sleep = real_sleep


def main() -> None:
    check_retry_policy()
    with TestClient(app, raise_server_exceptions=False) as client:
        # Bad input -> 422 in the envelope
        for name, kwargs in {
            "empty message": {"json": {"message": "", "conversation_id": "err_1"}},
            "message too long": {"json": {"message": "x" * 1001, "conversation_id": "err_1"}},
            "missing conversation_id": {"json": {"message": "hi"}},
            "not JSON": {"content": "this is not json", "headers": {"content-type": "application/json"}},
        }.items():
            r = client.post("/api/chat", **kwargs)
            b = r.json()
            check(f"422 envelope: {name}", r.status_code == 422 and is_envelope(b) and b["error"]["code"] == "invalid_request",
                  f"{r.status_code} {b}")
        r = client.post("/api/chat", json={"message": "", "conversation_id": "err_echo"})
        check("conversation_id echoed on 422 when present", r.json()["conversation_id"] == "err_echo")
        check("no input value echoed back", "x" * 20 not in client.post("/api/chat", json={"message": "x" * 1001, "conversation_id": "e"}).text)

        # Other routes keep FastAPI's default shape
        r = client.get("/dev/search", params={"q": "x", "source_type": "nope"})
        check("non-/api route keeps default 422 shape", r.status_code == 422 and "detail" in r.json())
        check("/health still ok", client.get("/health").json()["status"] == "ok")

        # Failures inside the workflow -> mapped codes and statuses
        original_graph, settings = chat_service.get_graph, get_settings()
        cases = [
            ("Mistral 429", FailingGraph(status_error(429)), 429, "rate_limited"),
            ("Mistral 503", FailingGraph(status_error(503)), 503, "upstream_unavailable"),
            ("Mistral bad key (401)", FailingGraph(status_error(401)), 503, "service_unavailable"),
            ("upstream timeout", FailingGraph(httpx.ReadTimeout("slow")), 504, "upstream_timeout"),
            ("network error", FailingGraph(httpx.ConnectError("down")), 503, "upstream_unavailable"),
            ("missing Mistral key", FailingGraph(MissingApiKeyError("MISTRAL_API_KEY is not set")), 503, "service_unavailable"),
            ("database error", FailingGraph(psycopg.OperationalError("connection refused password=secret")), 503, "service_unavailable"),
            ("unexpected bug", FailingGraph(RuntimeError("secret internals Traceback sk-12345")), 500, "internal_error"),
        ]
        try:
            for name, graph, status, code in cases:
                chat_service.get_graph = lambda g=graph: g
                r = client.post("/api/chat", json=GOOD)
                b = r.json()
                leaked = any(w in r.text for w in ("secret", "Traceback", "sk-12345", "password"))
                check(f"{name} -> {status} {code}", r.status_code == status and is_envelope(b)
                      and b["error"]["code"] == code and b["conversation_id"] == "err_1" and not leaked,
                      f"{r.status_code} {r.text[:200]}")

            old = settings.request_timeout_seconds
            settings.request_timeout_seconds = 0.3
            chat_service.get_graph = lambda: FailingGraph(delay=5)
            r = client.post("/api/chat", json=GOOD)
            settings.request_timeout_seconds = old
            check("request over its time budget -> 504 upstream_timeout",
                  r.status_code == 504 and r.json()["error"]["code"] == "upstream_timeout", f"{r.status_code} {r.text[:150]}")
        finally:
            chat_service.get_graph = original_graph


if __name__ == "__main__":
    main()
    print("\nRESULT:", "ALL PASS" if all(results) else "FAILURES")
    sys.exit(0 if all(results) else 1)
