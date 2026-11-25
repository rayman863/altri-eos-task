"""Structured JSON logging and the request/response logging middleware (plan 3.10).

Every request produces one JSON line with method, path, status, duration and (when
LOG_PAYLOADS is on) redacted request and response bodies up to LOG_BODY_LIMIT bytes.
SSE streams are never buffered: only their open/close is logged.
"""

import asyncio
import contextvars
import json
import logging
import re
import secrets
import sys
import time
from datetime import UTC, datetime
from typing import Any, TextIO

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.envelope import INTERNAL_ERROR_MESSAGE, error_body

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{6,64}$")
_SECRET_KEYS = re.compile(r"(password|secret|token|cookie|authorization|session)", re.I)
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
}
# Successful hits on these paths are logged at debug level: container healthchecks
# would otherwise bury real traffic in Dozzle.
_QUIET_PATHS = frozenset({"/healthz"})


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            entry["request_id"] = rid
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["traceback"] = self.formatException(record.exc_info)
        # json.dumps escapes newlines, so user text can't forge extra log lines.
        return json.dumps(entry, default=str, ensure_ascii=False)


def setup_logging(level: str, stream: TextIO = sys.stdout) -> None:
    """JSON logs on stdout for services. CLIs whose stdout is their output (the rules
    report) pass sys.stderr."""
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Uvicorn's own access log is off (--no-access-log); our middleware replaces it.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True


def new_request_id() -> str:
    return f"req_{secrets.token_hex(4)}"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if _SECRET_KEYS.search(str(k)) else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _body_for_log(raw: bytes, total_size: int, content_type: str, limit: int) -> Any:
    """Body as logged: None if empty, a size note if over the limit (never parsed, so
    a large body can't produce a huge log line), redacted JSON, or text."""
    if total_size == 0:
        return None
    if total_size > limit:
        return f"[{total_size} bytes, not logged: over the {limit}-byte limit]"
    if "json" in content_type:
        try:
            return _redact(json.loads(raw))
        except ValueError:
            pass
    return raw.decode("utf-8", errors="replace")


class TrustedProxies:
    """Peers whose X-Request-ID and X-Forwarded-For headers we believe (the Next.js
    server, by default the compose service `web`). Host names are resolved lazily and
    cached briefly, because a container's IP can change when it restarts."""

    def __init__(self, hosts: tuple[str, ...], ttl_s: float = 30.0) -> None:
        self.hosts = hosts
        self.ttl_s = ttl_s
        self._ips: frozenset[str] = frozenset()
        self._expires = 0.0

    async def contains(self, ip: str | None) -> bool:
        if not ip or not self.hosts:
            return False
        now = time.monotonic()
        if now >= self._expires:
            loop = asyncio.get_running_loop()
            ips: set[str] = set()
            for host in self.hosts:
                try:
                    infos = await loop.getaddrinfo(host, None)
                except OSError:
                    continue  # not running (yet): trust nothing from that name
                ips.update(str(info[4][0]) for info in infos)
            self._ips = frozenset(ips)
            self._expires = now + self.ttl_s
        return ip in self._ips


class RequestLogMiddleware:
    """Pure ASGI middleware: doesn't buffer responses, so streaming and SSE keep working.

    It also turns unhandled exceptions into the 500 error envelope itself. Starlette's
    own last-resort handler runs outside this middleware, after the request id is gone,
    so letting exceptions escape would produce 500s with no request id."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        log_payloads: bool,
        body_limit: int,
        trusted_proxy_hosts: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.log_payloads = log_payloads
        self.body_limit = body_limit
        self.trusted = TrustedProxies(trusted_proxy_hosts)
        self.log = logging.getLogger("eos.request")

    def _capture(self, buf: bytearray, chunk: bytes) -> None:
        # Keep at most limit + 1 bytes: enough to know the body was over the limit.
        room = self.body_limit + 1 - len(buf)
        if room > 0:
            buf.extend(chunk[:room])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode(errors="replace") for k, v in scope["headers"]}
        peer = (scope.get("client") or (None,))[0]
        trusted = await self.trusted.contains(peer)
        incoming = headers.get("x-request-id", "") if trusted else ""
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else new_request_id()
        # The proxy appends the address it saw; anything before that came from the client
        # and can be forged, so only the last entry is trusted.
        forwarded = headers.get("x-forwarded-for", "").split(",")[-1].strip() if trusted else ""
        client_ip = forwarded or peer or "?"
        # Shared with route code via request.state: the rate limiter must key on this
        # resolved address, not request.client (which is the web container for proxied calls).
        scope.setdefault("state", {}).update(request_id=request_id, client_ip=client_ip)
        token = request_id_var.set(request_id)

        started = time.perf_counter()
        req_body, resp_body = bytearray(), bytearray()
        sizes = {"request": 0, "response": 0}
        # status stays None if the request ends without any response (e.g. client gone).
        state: dict[str, Any] = {"status": None, "content_type": "", "streaming": False}

        async def receive_wrapper() -> Message:
            message = await receive()
            if self.log_payloads and message["type"] == "http.request":
                chunk = message.get("body", b"")
                sizes["request"] += len(chunk)
                self._capture(req_body, chunk)
            return message

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                raw_headers = list(message.get("headers", []))
                for key, value in raw_headers:
                    if key.lower() == b"content-type":
                        state["content_type"] = value.decode(errors="replace")
                state["streaming"] = "text/event-stream" in state["content_type"]
                raw_headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = raw_headers
                if state["streaming"]:
                    self.log.info(
                        "sse stream opened",
                        extra={"method": scope["method"], "path": scope["path"]},
                    )
            elif (
                message["type"] == "http.response.body"
                and self.log_payloads
                and not state["streaming"]
            ):
                chunk = message.get("body", b"")
                sizes["response"] += len(chunk)
                self._capture(resp_body, chunk)
            await send(message)

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        except Exception as exc:
            self.log.error(
                "unhandled error",
                exc_info=exc,
                extra={"method": scope["method"], "path": scope["path"]},
            )
            if state["status"] is not None:
                raise  # response already started; nothing sane left to send
            body = json.dumps(
                error_body("internal_error", INTERNAL_ERROR_MESSAGE, request_id)
            ).encode()
            await send_wrapper(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send_wrapper({"type": "http.response.body", "body": body})
        finally:
            status = state["status"]
            entry: dict[str, Any] = {
                "method": scope["method"],
                "path": scope["path"],
                "query": scope.get("query_string", b"").decode(errors="replace") or None,
                "status": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "client_ip": client_ip,
            }
            if self.log_payloads:
                entry["request_body"] = _body_for_log(
                    bytes(req_body),
                    sizes["request"],
                    headers.get("content-type", ""),
                    self.body_limit,
                )
                if not state["streaming"]:
                    entry["response_body"] = _body_for_log(
                        bytes(resp_body), sizes["response"], state["content_type"], self.body_limit
                    )
            if state["streaming"]:
                msg = "sse stream closed"
            elif status is None:
                msg = "request ended without a response"
            else:
                msg = "request"
            quiet = scope["path"] in _QUIET_PATHS and status is not None and status < 400
            self.log.log(logging.DEBUG if quiet else logging.INFO, msg, extra=entry)
            request_id_var.reset(token)
