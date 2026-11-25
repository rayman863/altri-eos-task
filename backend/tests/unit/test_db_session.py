"""The request session commits before the response is sent (plan 3.12 item 4).

Pure ASGI against a tiny app wired like app.main, with a fake session that records what
happens, so no database is needed. The point: a 2xx is only sent after the commit, and a
commit that fails becomes a 500 instead of a silent 200.
"""

from typing import Any

from fastapi import FastAPI

from app.db import DbSession
from app.errors import AppError, install_error_handlers
from app.logging import RequestLogMiddleware
from tests.helpers import call


class FakeTransaction:
    def __init__(self, events: list[str], fail_commit: bool) -> None:
        self.events = events
        self.fail_commit = fail_commit

    async def __aenter__(self) -> "FakeTransaction":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is not None:
            self.events.append("rollback")
            return
        if self.fail_commit:
            self.events.append("commit failed")
            raise RuntimeError("could not serialize access")
        self.events.append("commit")


class FakeSession:
    """Stands in for AsyncSession in `async with sessionmaker() as s, s.begin()`."""

    def __init__(self, events: list[str], fail_commit: bool) -> None:
        self.events = events
        self.fail_commit = fail_commit

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.events.append("close")

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self.events, self.fail_commit)


def make_app(events: list[str], *, fail_commit: bool = False) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(
        RequestLogMiddleware, log_payloads=False, body_limit=100, trusted_proxy_hosts=()
    )
    app.state.sessionmaker = lambda: FakeSession(events, fail_commit)

    @app.post("/write")
    async def write(session: DbSession) -> dict[str, bool]:
        events.append("handler")
        return {"ok": True}

    @app.post("/missing")
    async def missing(session: DbSession) -> None:
        events.append("handler")
        raise AppError(404, "not_found", "No such row.")

    return app


def run(app: FastAPI, path: str, events: list[str]) -> int | None:
    def on_send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            events.append(f"response {message['status']}")

    status, _, _ = call(app, path, method="POST", on_send=on_send)
    return status


def test_commit_happens_before_the_response_is_sent():
    events: list[str] = []
    assert run(make_app(events), "/write", events) == 200
    assert events == ["handler", "commit", "close", "response 200"]


def test_a_failed_commit_is_a_500_not_a_200():
    events: list[str] = []
    assert run(make_app(events, fail_commit=True), "/write", events) == 500
    assert events == ["handler", "commit failed", "close", "response 500"]


def test_an_app_error_rolls_back_before_its_response():
    events: list[str] = []
    assert run(make_app(events), "/missing", events) == 404
    assert events == ["handler", "rollback", "close", "response 404"]
