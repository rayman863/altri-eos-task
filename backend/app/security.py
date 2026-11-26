"""Session cookie and request guards (plan 3.15).

- Session: `eos_session` = base64url(JSON {uid, ep, iat}) + "." + HMAC-SHA256 over it, keyed by
  SESSION_SECRET. Stdlib `hmac` instead of itsdangerous (same construction, one dependency
  fewer). The server checks the signature and the 12 h age; the cookie is HttpOnly and
  SameSite=Lax.
- ApiGuardMiddleware, for everything under /api/v1:
  * writes (POST/PUT/PATCH/DELETE) must be JSON (415), carry `X-EOS-CSRF: 1` and, if the
    browser sent an `Origin`, come from WEB_ORIGIN (403 csrf_failed);
  * request bodies over MAX_BODY_BYTES give 413;
  * responses get nosniff, Referrer-Policy: no-referrer and Cache-Control: no-store.
"""

import base64
import hashlib
import hmac
import json
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.clock import wall_clock
from app.envelope import error_body
from app.logging import request_id_var

COOKIE_NAME = "eos_session"
API_PREFIX = "/api/v1"
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_HEADER = b"x-eos-csrf"


# ---- session tokens ---------------------------------------------------------------------


def _real_seconds() -> int:
    """Real time, on purpose: a cookie's age is about its lifetime, not about EOS weeks, so
    it uses the wall clock (through clock.py, the only module allowed to read it)."""
    return int(wall_clock().timestamp())


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(secret: str, payload: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode("ascii"), hashlib.sha256).digest())


def sign_session(secret: str, user_id: str, epoch: int = 0, issued_at: int | None = None) -> str:
    """`epoch` is the user's `session_epoch`: logout bumps it, which ends every session the
    user has (the token alone can't be revoked, so the server compares this number)."""
    body = {
        "uid": user_id,
        "ep": epoch,
        "iat": _real_seconds() if issued_at is None else issued_at,
    }
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_signature(secret, payload)}"


def verify_session(
    secret: str, token: str, max_age_s: int, now: float | None = None
) -> tuple[str, int] | None:
    """(user id, session epoch) of a valid, unexpired token; None for anything else. The
    caller still checks the epoch against the user's current one.

    Session age uses the real wall clock, not the business clock (APP_NOW): it is about
    the cookie's lifetime, not about EOS weeks."""
    try:
        payload, signature = token.split(".", 1)
        if not hmac.compare_digest(signature, _signature(secret, payload)):
            return None
        body = json.loads(_unb64(payload))
        user_id, epoch, issued_at = body["uid"], body["ep"], body["iat"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(user_id, str) or type(epoch) is not int or type(issued_at) is not int:
        return None
    current = _real_seconds() if now is None else now
    if not issued_at - 60 <= current <= issued_at + max_age_s:  # small skew allowance
        return None
    return user_id, epoch


def session_cookie(token: str, *, max_age_s: int, secure: bool) -> str:
    parts = [f"{COOKIE_NAME}={token}", "HttpOnly", "SameSite=Lax", "Path=/", f"Max-Age={max_age_s}"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_session_cookie(*, secure: bool) -> str:
    return session_cookie("", max_age_s=0, secure=secure)


# ---- request guard ------------------------------------------------------------------------


class ApiGuardMiddleware:
    """Pure ASGI, inside RequestLogMiddleware (so errors carry the request id)."""

    def __init__(self, app: ASGIApp, *, web_origins: tuple[str, ...], max_body_bytes: int) -> None:
        self.app = app
        self.web_origins = frozenset(o.rstrip("/").encode() for o in web_origins)
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(API_PREFIX):
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        method = scope["method"]

        declared = headers.get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.max_body_bytes):
            await self._reject(send, 413, "payload_too_large", "Request body is too large.")
            return

        if method in WRITE_METHODS:
            content_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
            if content_type != b"application/json":
                await self._reject(
                    send, 415, "unsupported_media_type", "Writes must be application/json."
                )
                return
            if headers.get(CSRF_HEADER) != b"1":
                await self._reject(send, 403, "csrf_failed", "Missing X-EOS-CSRF header.")
                return
            origin = headers.get(b"origin")
            if origin is not None and origin.rstrip(b"/") not in self.web_origins:
                await self._reject(send, 403, "csrf_failed", "Request origin is not allowed.")
                return

        # Read the body up front (it is small by definition) so the size limit also holds
        # for chunked requests without a Content-Length, then replay it to the app.
        body = bytearray()
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            more = message.get("more_body", False)
            if len(body) > self.max_body_bytes:
                await self._reject(send, 413, "payload_too_large", "Request body is too large.")
                return

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()  # after the body: wait for a disconnect

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                ]
                present = {k.lower() for k, _ in message.get("headers", [])}
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        *(h for h in extra if h[0] not in present),
                    ],
                }
            await send(message)

        await self.app(scope, replay, send_with_headers)

    @staticmethod
    async def _reject(send: Send, status: int, code: str, message: str) -> None:
        payload: dict[str, Any] = error_body(code, message, request_id_var.get())
        raw = json.dumps(payload).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(raw)).encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": raw})
