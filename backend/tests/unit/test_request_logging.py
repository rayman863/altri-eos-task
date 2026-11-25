"""Request logging middleware and the error envelope (plan 3.10, API contracts section 1).

Pure ASGI calls against a tiny app wired exactly like app.main: no server, no database.
"""

import asyncio
import json
import logging
from typing import Any

import pytest
from fastapi import FastAPI, Request
from pydantic import BaseModel

from app.errors import install_error_handlers
from app.logging import RequestLogMiddleware

PEER = "172.30.0.9"


class Item(BaseModel):
    name: str
    priority: int


def make_app(*, trusted: tuple[str, ...] = (), body_limit: int = 100) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(
        RequestLogMiddleware,
        log_payloads=True,
        body_limit=body_limit,
        trusted_proxy_hosts=trusted,
    )

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/state")
    async def state(request: Request) -> dict[str, str]:
        return {"client_ip": request.state.client_ip, "request_id": request.state.request_id}

    @app.post("/items")
    async def create(item: Item) -> dict[str, Any]:
        return item.model_dump()

    return app


def call(
    asgi: Any,
    path: str,
    *,
    method: str = "GET",
    headers: list[tuple[bytes, bytes]] | None = None,
    body: bytes = b"",
    disconnect: bool = False,
) -> tuple[int | None, dict[str, str], Any]:
    sent: list[dict[str, Any]] = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "client": (PEER, 1234),
        "server": ("test", 80),
    }

    async def receive() -> dict[str, Any]:
        if disconnect:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(asgi(scope, receive, send))
    start = next((m for m in sent if m["type"] == "http.response.start"), None)
    if start is None:
        return None, {}, None
    response_headers = {k.decode(): v.decode() for k, v in start["headers"]}
    raw = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], response_headers, json.loads(raw) if raw else None


def request_logs(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "eos.request"]


def test_unhandled_error_gets_the_envelope_with_its_request_id(caplog):
    caplog.set_level(logging.DEBUG)
    status, headers, body = call(make_app(), "/boom")
    assert status == 500
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["request_id"] == headers["x-request-id"]
    assert headers["x-request-id"].startswith("req_")
    error = next(r for r in request_logs(caplog) if r.getMessage() == "unhandled error")
    assert error.exc_info is not None  # traceback goes to the logs only
    assert "kaboom" not in json.dumps(body)


def test_404_uses_the_envelope():
    status, headers, body = call(make_app(), "/nope")
    assert status == 404
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"] == headers["x-request-id"]


def test_malformed_json_is_400_bad_request():
    status, _, body = call(
        make_app(),
        "/items",
        method="POST",
        headers=[(b"content-type", b"application/json")],
        body=b"{bad",
    )
    assert status == 400
    assert body["error"]["code"] == "bad_request"


def test_invalid_fields_are_422_with_field_list():
    status, _, body = call(
        make_app(),
        "/items",
        method="POST",
        headers=[(b"content-type", b"application/json")],
        body=b'{"name": "x", "priority": "high"}',
    )
    assert status == 422
    assert body["error"]["code"] == "validation_failed"
    assert body["error"]["details"]["fields"][0]["loc"] == ["body", "priority"]


def test_successful_healthcheck_is_logged_at_debug(caplog):
    caplog.set_level(logging.DEBUG)
    call(make_app(), "/healthz")
    assert [r.levelno for r in request_logs(caplog)] == [logging.DEBUG]


def test_large_bodies_are_summarised_not_logged(caplog):
    caplog.set_level(logging.INFO)
    payload = json.dumps({"name": "x" * 200, "priority": 1}).encode()
    call(
        make_app(body_limit=100),
        "/items",
        method="POST",
        headers=[(b"content-type", b"application/json")],
        body=payload,
    )
    record = request_logs(caplog)[-1]
    assert record.request_body.startswith(f"[{len(payload)} bytes, not logged")


def test_small_json_bodies_are_logged_with_secrets_redacted(caplog):
    caplog.set_level(logging.INFO)
    app = make_app()

    @app.post("/login")
    async def login(request: Request) -> dict[str, str]:
        await request.body()
        return {"ok": "yes"}

    call(
        app,
        "/login",
        method="POST",
        headers=[(b"content-type", b"application/json")],
        body=b'{"user_id": "u3", "password": "hunter2"}',
    )
    assert request_logs(caplog)[-1].request_body == {"user_id": "u3", "password": "[redacted]"}


def test_headers_from_an_untrusted_peer_are_ignored():
    status, headers, body = call(
        make_app(trusted=("web-not-running",)),
        "/state",
        headers=[(b"x-request-id", b"req_spoofed1"), (b"x-forwarded-for", b"10.9.9.9")],
    )
    assert status == 200
    assert headers["x-request-id"] != "req_spoofed1"
    assert body == {"client_ip": PEER, "request_id": headers["x-request-id"]}


def test_trusted_proxy_headers_are_used_with_the_last_forwarded_entry():
    _, headers, body = call(
        make_app(trusted=(PEER,)),
        "/state",
        headers=[
            (b"x-request-id", b"req_fromweb1"),
            # The browser forged the first entry; the proxy appended the real address.
            (b"x-forwarded-for", b"6.6.6.6, 203.0.113.7"),
        ],
    )
    assert headers["x-request-id"] == "req_fromweb1"
    assert body == {"client_ip": "203.0.113.7", "request_id": "req_fromweb1"}


def test_request_without_any_response_is_not_logged_as_500(caplog):
    caplog.set_level(logging.INFO)

    async def silent_app(scope, receive, send):
        return None

    middleware = RequestLogMiddleware(silent_app, log_payloads=False, body_limit=100)
    status, _, _ = call(middleware, "/gone")
    assert status is None
    record = request_logs(caplog)[-1]
    assert record.getMessage() == "request ended without a response"
    assert record.status is None
