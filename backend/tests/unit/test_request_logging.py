"""Request logging middleware and the error envelope (plan 3.10, API contracts section 1).

Pure ASGI calls against a tiny app wired exactly like app.main: no server, no database.
"""

import json
import logging
from typing import Any

import pytest
from fastapi import FastAPI, Request
from pydantic import BaseModel

from app.errors import install_error_handlers
from app.logging import RequestLogMiddleware
from tests.helpers import PEER, call


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

    @app.get("/whoami")
    async def whoami(request: Request) -> dict[str, str]:
        request.state.user_id = "u3"  # what app.authz does after verifying the session
        return {"ok": "yes"}

    @app.get("/state")
    async def state(request: Request) -> dict[str, str]:
        return {"client_ip": request.state.client_ip, "request_id": request.state.request_id}

    @app.post("/items")
    async def create(item: Item) -> dict[str, Any]:
        return item.model_dump()

    return app


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
        make_app(trusted=("web-not-running.invalid",)),  # .invalid fails fast
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


def test_requests_without_proxy_headers_skip_the_trust_lookup():
    # A missing `web` container takes seconds to fail in Docker DNS; healthchecks and
    # direct calls carry no proxy headers, so they must not wait on that lookup.
    import time

    app = make_app(trusted=("no-such-host.invalid",))
    started = time.perf_counter()
    status, _, _ = call(app, "/healthz")
    assert status == 200
    assert time.perf_counter() - started < 0.4


def test_trust_lookups_are_capped():
    import time

    app = make_app(trusted=("no-such-host.invalid",))
    started = time.perf_counter()
    status, headers, _ = call(app, "/healthz", headers=[(b"x-request-id", b"req_forged01")])
    assert status == 200
    assert headers["x-request-id"] != "req_forged01"  # untrusted peer: id not believed
    assert time.perf_counter() - started < 1.5


def test_the_signed_in_user_is_in_the_request_log(caplog):
    caplog.set_level(logging.INFO)
    call(make_app(), "/whoami")
    call(make_app(), "/state")  # no session: user_id is null
    entries = [r for r in request_logs(caplog) if r.getMessage() == "request"]
    assert [getattr(r, "user_id", "missing") for r in entries] == ["u3", None]
