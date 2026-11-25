"""Small helpers shared by the test suites."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

PEER = "172.30.0.9"


def utc(value: str) -> datetime:
    """'2026-11-09T05:59:00Z' -> aware UTC datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def call(
    asgi: Any,
    path: str,
    *,
    method: str = "GET",
    headers: list[tuple[bytes, bytes]] | None = None,
    body: bytes = b"",
    disconnect: bool = False,
    on_send: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[int | None, dict[str, str], Any]:
    """One pure-ASGI request (no server, no httpx). `on_send` sees every message as it is
    sent, so a test can tell what happened before the response started."""
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
        if on_send is not None:
            on_send(message)
        sent.append(message)

    asyncio.run(asgi(scope, receive, send))
    start = next((m for m in sent if m["type"] == "http.response.start"), None)
    if start is None:
        return None, {}, None
    response_headers = {k.decode(): v.decode() for k, v in start["headers"]}
    raw = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], response_headers, json.loads(raw) if raw else None
