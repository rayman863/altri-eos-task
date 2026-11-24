"""Structured JSON logging and the request/response logging middleware (plan 3.10).

Every request produces one JSON line with method, path, status, duration and (when
LOG_PAYLOADS is on) truncated, redacted request and response bodies. SSE streams are
never buffered: only their open/close is logged.
"""

import contextvars
import json
import logging
import re
import secrets
import sys
import time
from datetime import UTC, datetime
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{6,64}$")
_SECRET_KEYS = re.compile(r"(password|secret|token|cookie|authorization|session)", re.I)
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
}


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


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
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


def _body_for_log(raw: bytes, content_type: str, limit: int) -> Any:
    if not raw:
        return None
    if "json" in content_type:
        try:
            return _redact(json.loads(raw))
        except ValueError:
            pass
    text = raw[:limit].decode("utf-8", errors="replace")
    return text + ("…[truncated]" if len(raw) > limit else "")


class RequestLogMiddleware:
    """Pure ASGI middleware: doesn't buffer responses, so streaming and SSE keep working."""

    def __init__(self, app: ASGIApp, *, log_payloads: bool, body_limit: int) -> None:
        self.app = app
        self.log_payloads = log_payloads
        self.body_limit = body_limit
        self.log = logging.getLogger("eos.request")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode(errors="replace") for k, v in scope["headers"]}
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else new_request_id()
        token = request_id_var.set(request_id)

        started = time.perf_counter()
        req_body = bytearray()
        resp_body = bytearray()
        state: dict[str, Any] = {"status": 500, "content_type": "", "streaming": False}

        async def receive_wrapper() -> Message:
            message = await receive()
            if (
                self.log_payloads
                and message["type"] == "http.request"
                and len(req_body) <= self.body_limit
            ):
                req_body.extend(message.get("body", b""))
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
                and len(resp_body) <= self.body_limit
            ):
                resp_body.extend(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        finally:
            entry: dict[str, Any] = {
                "method": scope["method"],
                "path": scope["path"],
                "query": scope.get("query_string", b"").decode(errors="replace") or None,
                "status": state["status"],
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "client_ip": headers.get("x-forwarded-for") or (scope.get("client") or ("?",))[0],
            }
            if self.log_payloads:
                entry["request_body"] = _body_for_log(
                    bytes(req_body), headers.get("content-type", ""), self.body_limit
                )
                if not state["streaming"]:
                    entry["response_body"] = _body_for_log(
                        bytes(resp_body), state["content_type"], self.body_limit
                    )
            msg = "sse stream closed" if state["streaming"] else "request"
            self.log.info(msg, extra=entry)
            request_id_var.reset(token)
