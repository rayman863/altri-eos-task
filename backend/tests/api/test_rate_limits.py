"""Rate limits (layer L4, plan 3.15), against the test stack's real Redis.

The suite runs with RATE_LIMIT_ENABLED=false; these tests give their app a limiter of its
own, under a fresh key prefix, so they never see each other's counters.
"""

import asyncio
import secrets

import pytest

import app.ratelimit as ratelimit
from app.cache import Cache
from app.main import create_app
from app.ratelimit import LIMITS, RateLimiter
from tests.api.conftest import Client, asgi_request, wire_for_tests

SCORE = "/teams/team_lead/measurables/m1/scores/2026-11-02"


def limiter(seeded, url: str | None = None) -> RateLimiter:
    return RateLimiter(url or seeded.redis_url, f"test-{secrets.token_hex(4)}", "eos-test:rl")


@pytest.fixture
def limited(app, seeded):
    """The API app with rate limits on."""
    app.state.rate_limiter = limiter(seeded)
    return app


def login_from(app, address: str, user: str = "u3"):
    return asyncio.run(
        asgi_request(
            app,
            "POST",
            "/api/v1/auth/login",
            json={"user_id": user},
            headers={"x-eos-csrf": "1", "x-forwarded-for": address},
        )
    )


def test_ten_logins_a_minute_per_address_then_429_with_retry_after(seeded):
    # The address comes from X-Forwarded-For, believed only from a trusted proxy (here the
    # test client's own address, standing in for the Next.js server).
    app = create_app(seeded.model_copy(update={"trusted_proxy_hosts": "127.0.0.1"}))
    engine = wire_for_tests(app, seeded)
    app.state.rate_limiter = limiter(seeded)
    try:
        for _ in range(LIMITS["login"]):
            assert login_from(app, "10.0.0.1").status == 200
        refused = login_from(app, "10.0.0.1")
        assert (refused.status, refused.body["error"]["code"]) == (429, "rate_limited")
        assert 1 <= int(refused.headers["retry-after"]) <= 60
        assert login_from(app, "10.0.0.2").status == 200  # another browser isn't affected
    finally:
        asyncio.run(engine.dispose())


def test_writes_are_limited_per_user_and_reads_never(limited, login, monkeypatch):
    monkeypatch.setitem(LIMITS, "write", 3)
    u3, u2 = login("u3"), login("u2")  # logins count in their own bucket
    for value in ("1", "2", "3"):
        assert u3.put(SCORE, {"value": value}).status == 200
    refused = u3.put(SCORE, {"value": "4"})
    assert (refused.status, refused.error) == (429, "rate_limited")
    assert "retry-after" in refused.headers
    assert u2.put(SCORE, {"value": "5"}).status == 200  # a different user
    for _ in range(5):
        assert u3.get("/teams/team_lead/scorecard").status == 200  # reads aren't limited


def test_make_it_an_issue_has_its_own_tighter_bucket(limited, login, monkeypatch):
    monkeypatch.setitem(LIMITS, "make_issue", 2)
    u3 = login("u3")
    make = "/teams/team_lead/measurables/m1/scores/2026-10-26/issue"
    assert u3.post(make).status in (200, 201)
    assert u3.post(make).status in (200, 201)
    assert u3.post(make).error == "rate_limited"
    assert u3.put(SCORE, {"value": "7"}).status == 200  # other writes have their own budget


def test_a_request_without_a_valid_session_is_refused_by_auth_not_counted(limited, monkeypatch):
    monkeypatch.setitem(LIMITS, "write", 1)
    anon = Client(limited)
    for _ in range(3):
        assert anon.put(SCORE, {"value": "1"}).error == "unauthenticated"


def test_redis_down_lets_requests_through(app, login, seeded, monkeypatch):
    monkeypatch.setitem(LIMITS, "write", 1)
    app.state.rate_limiter = limiter(seeded, "redis://127.0.0.1:1/0")
    u3 = login("u3")
    for value in ("1", "2", "3"):
        assert u3.put(SCORE, {"value": value}).status == 200
    assert not app.state.rate_limiter.available()  # the breaker skips Redis for a while


def test_windows_are_one_minute_and_counters_expire(seeded):
    rl = limiter(seeded)

    async def main() -> list:
        start = 1_800_000_000.0  # a window boundary (divisible by 60)
        LIMITS["probe"] = 2
        try:
            results = [await rl.over_limit("probe", "u1", start + s) for s in (0, 10, 59)]
            results.append(await rl.over_limit("probe", "u1", start + 60))  # next window
            ttl = await rl.call(lambda r: r.ttl(f"{rl.prefix}:probe:u1:{int(start // 60)}"))
        finally:
            del LIMITS["probe"]
            await rl.close()
        return [*results, ttl]

    first, second, third, next_window, ttl = asyncio.run(main())
    assert (first, second) == (None, None)
    assert third == 1  # over the limit at second 59: retry in 1 s
    assert next_window is None
    assert 0 < ttl <= ratelimit.WINDOW_S + 5


def test_logout_is_never_limited_so_it_always_ends_the_session(limited, login, monkeypatch):
    """The web app drops its cookie whatever the API answers, so a refused logout would
    leave the server-side session valid (a copied cookie would keep working)."""
    monkeypatch.setitem(LIMITS, "write", 1)
    u3 = login("u3")
    assert u3.put(SCORE, {"value": "1"}).status == 200
    assert u3.put(SCORE, {"value": "2"}).error == "rate_limited"  # the budget is spent
    stale = Client(limited, u3.token)
    assert u3.post("/auth/logout").status == 204
    assert stale.get("/me").error == "unauthenticated"


def test_healthz_reports_redis_for_the_rate_limits_when_the_cache_is_off(app, seeded):
    app.state.cache = Cache(None, "")
    app.state.rate_limiter = limiter(seeded, "redis://127.0.0.1:1/0")
    health = asyncio.run(asgi_request(app, "GET", "/healthz"))
    assert (health.status, health.body["status"], health.body["redis"]) == (
        200,
        "degraded",
        "degraded",
    )
