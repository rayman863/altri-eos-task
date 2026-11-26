"""API tests: the real app (create_app) against eos_test, driven over pure ASGI.

No server and no HTTP library: requests go straight into the ASGI app, through every
middleware, guard and route that ships. The app gets a NullPool engine (fresh connection
per checkout, so each test's event loop is independent) and a frozen clock at APP_NOW.
Each test starts from a freshly reset seed.
"""

import asyncio
import contextlib
import json as jsonlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI

from app.clock import FrozenClock, parse_app_now
from app.db import make_sessionmaker
from app.main import create_app
from tests.db.conftest import engine_for, migrated, reseed, seeded, settings  # noqa: F401

CSRF = {"x-eos-csrf": "1"}


@dataclass
class Resp:
    status: int
    headers: dict[str, str]
    body: Any
    raw: bytes
    cookies: list[str] = field(default_factory=list)

    @property
    def error(self) -> str | None:
        return (
            self.body["error"]["code"]
            if isinstance(self.body, dict) and "error" in self.body
            else None
        )


async def asgi_request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json: Any = None,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    cookie: str | None = None,
    disconnect_after: float = 10.0,
    on_send: Callable[[dict[str, Any]], None] | None = None,
) -> Resp:
    path_only, _, query = path.partition("?")
    payload = body if body is not None else (b"" if json is None else jsonlib.dumps(json).encode())
    hdrs = {k.lower(): v for k, v in (headers or {}).items()}
    if json is not None and "content-type" not in hdrs:
        hdrs["content-type"] = "application/json"
    if payload and "content-length" not in hdrs:
        hdrs["content-length"] = str(len(payload))
    if cookie:
        hdrs["cookie"] = f"eos_session={cookie}"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path_only,
        "raw_path": path_only.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": [(k.encode(), v.encode()) for k, v in hdrs.items()],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
    }
    sent: list[dict[str, Any]] = []
    delivered = False
    finished = asyncio.Event()

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": payload, "more_body": False}
        # After the body the client "stays connected" until the response is complete, or
        # at most `disconnect_after` seconds (streaming tests pass a short value), so code
        # that waits for a disconnect (SSE) ends instead of hanging the run.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(finished.wait(), timeout=disconnect_after)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if on_send is not None:
            on_send(message)
        sent.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            finished.set()

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    raw = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    out_headers: dict[str, str] = {}
    cookies: list[str] = []
    for k, v in start["headers"]:
        name, value = k.decode().lower(), v.decode()
        if name == "set-cookie":
            cookies.append(value)
        out_headers[name] = value
    parsed = (
        jsonlib.loads(raw)
        if raw and out_headers.get("content-type", "").startswith("application/json")
        else None
    )
    return Resp(start["status"], out_headers, parsed, raw, cookies)


def session_token(resp: Resp) -> str | None:
    for c in resp.cookies:
        name, _, rest = c.partition("=")
        if name == "eos_session":
            value = rest.split(";", 1)[0].strip('"')
            return value or None  # a cleared cookie is eos_session=""
    return None


class Client:
    """Sync facade for one signed-in (or anonymous) browser. Writes send the CSRF header
    and JSON content type by default, like the Next.js server's API client."""

    def __init__(self, app: FastAPI, token: str | None = None) -> None:
        self.app = app
        self.token = token

    def request(self, method: str, path: str, json: Any = None, **kwargs: Any) -> Resp:
        headers = dict(kwargs.pop("headers", {}) or {})
        # A live stream (GET .../events) ends after this; other responses finish first.
        kwargs.setdefault("disconnect_after", 1.0)
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            headers = {**CSRF, "content-type": "application/json", **headers}
            if json is None and "body" not in kwargs:
                json = {}
        return asyncio.run(
            asgi_request(
                self.app,
                method,
                f"/api/v1{path}",
                json=json,
                headers=headers,
                cookie=self.token,
                **kwargs,
            )
        )

    def get(self, path: str, **kw: Any) -> Resp:
        return self.request("GET", path, **kw)

    def post(self, path: str, json: Any = None, **kw: Any) -> Resp:
        return self.request("POST", path, json, **kw)

    def put(self, path: str, json: Any = None, **kw: Any) -> Resp:
        return self.request("PUT", path, json, **kw)

    def patch(self, path: str, json: Any = None, **kw: Any) -> Resp:
        return self.request("PATCH", path, json, **kw)

    def delete(self, path: str, **kw: Any) -> Resp:
        return self.request("DELETE", path, **kw)


@pytest.fixture
def app(seeded) -> FastAPI:  # noqa: F811 - the imported fixture
    application = create_app(seeded)
    engine = engine_for(seeded.database_url)  # eos_app, like the real API
    application.state.engine = engine
    application.state.sessionmaker = make_sessionmaker(engine)
    application.state.clock = FrozenClock(parse_app_now(seeded.app_now))
    yield application
    asyncio.run(engine.dispose())


@pytest.fixture
def anon(app) -> Client:
    return Client(app)


@pytest.fixture
def login(app):
    """`login("u3")` -> a Client signed in through the real POST /auth/login."""

    def _login(user_id: str) -> Client:
        resp = Client(app).post("/auth/login", {"user_id": user_id})
        assert resp.status == 200, resp.body
        return Client(app, session_token(resp))

    return _login
