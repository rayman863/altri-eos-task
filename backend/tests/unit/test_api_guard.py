"""ApiGuardMiddleware's Origin check with several allowed origins (WEB_ORIGIN is a list:
localhost and PUBLIC_HOST on WEB_PORT by default)."""

import pytest
from fastapi import FastAPI

from app.config import Settings
from app.errors import install_error_handlers
from app.security import ApiGuardMiddleware
from tests.helpers import call

ORIGINS = ("http://localhost:3001", "http://192.168.1.5:3001")


def make_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(ApiGuardMiddleware, web_origins=ORIGINS, max_body_bytes=1024)

    @app.post("/api/v1/write")
    async def write() -> dict[str, bool]:
        return {"ok": True}

    return app


def post(origin: str | None) -> int | None:
    headers = [(b"content-type", b"application/json"), (b"x-eos-csrf", b"1")]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    status, _, _ = call(make_app(), "/api/v1/write", method="POST", headers=headers, body=b"{}")
    return status


@pytest.mark.parametrize(
    ("origin", "status"),
    [
        ("http://localhost:3001", 200),
        ("http://192.168.1.5:3001/", 200),  # trailing slash tolerated
        (None, 200),  # server-to-server (Next.js server actions, curl): no Origin
        ("http://localhost:3000", 403),  # the old port
        ("http://evil.localhost:3001", 403),
        ("null", 403),  # sandboxed iframes and file:// pages
    ],
)
def test_only_listed_origins_may_write(origin, status):
    assert post(origin) == status


def test_web_origin_setting_is_a_comma_separated_list():
    settings = Settings(web_origin=" http://localhost:3001/ , http://192.168.1.5:3001,")
    assert settings.web_origin_list == ORIGINS
