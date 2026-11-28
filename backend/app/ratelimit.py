"""Rate limits on Redis (plan 3.15, layer L4): fixed one-minute windows.

| Bucket       | What                                  | Limit         | Keyed on          |
|--------------|---------------------------------------|---------------|-------------------|
| `login`      | POST /auth/login                      | 10 per minute | the client address |
| `make_issue` | POST .../scores/{week}/issue          | 30 per minute | the signed-in user |
| `write`      | every other POST, PUT, PATCH, DELETE  | 120 per minute| the signed-in user |

Logout is never limited (it only takes access away).
Open live streams are limited separately (5 per user on each API worker, app/realtime.py).

- The client address is the one the request middleware resolved (`request.state.client_ip`:
  the browser's, forwarded by the Next.js server), never the TCP peer, which is the web
  container for every proxied call.
- The user is the id in the session cookie's signature, checked here without a database
  query; a request without a valid session isn't counted (it is refused with 401 anyway).
- Over the limit: 429 `rate_limited` with `Retry-After` (seconds to the next window).
- Redis down: fail open (the request goes through) and log a warning, with the same 50 ms
  budget and breaker as the cache. A limiter must never be what takes the app down.
- Counters are per database (`eos:<database>:rl:...`), so the demo and the E2E stack never
  share them, and wall-clock based (the business clock may be frozen).
- `RATE_LIMIT_ENABLED=false` switches it off; the test suite does, except in its tests.
"""

from typing import Any

import redis.asyncio as redis
from fastapi import Request
from sqlalchemy.engine import make_url

from app.cache import FAILED, RedisPool
from app.clock import wall_clock
from app.config import Settings
from app.errors import AppError
from app.security import API_PREFIX, COOKIE_NAME, verify_session

WINDOW_S = 60
LIMITS = {"login": 10, "make_issue": 30, "write": 120}
WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
LOGIN_PATH = f"{API_PREFIX}/auth/login"
# Never limited: logging out only takes access away, and the web app drops its cookie
# whatever the API answers, so a refused logout would leave the session valid on the server.
EXEMPT = frozenset({f"{API_PREFIX}/auth/logout"})


class RateLimiter(RedisPool):
    """One per worker (`app.state.rate_limiter`)."""

    fallback = "allowing requests without rate limits"

    def __init__(self, url: str | None, database: str, client_name: str) -> None:
        super().__init__(url, client_name)
        self.prefix = f"eos:{database}:rl"

    @classmethod
    def from_settings(cls, settings: Settings, client_name: str) -> "RateLimiter":
        url = settings.redis_url if settings.rate_limit_enabled else None
        return cls(url, make_url(settings.database_url).database or "", client_name)

    async def over_limit(self, bucket: str, subject: str, now: float | None = None) -> int | None:
        """Count one request; the seconds until the window ends if that was one too many,
        else None (also when Redis can't be reached)."""
        now = wall_clock().timestamp() if now is None else now
        window = int(now // WINDOW_S)
        key = f"{self.prefix}:{bucket}:{subject}:{window}"

        async def count(r: redis.Redis) -> Any:
            async with r.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, WINDOW_S + 5, nx=True)
                return (await pipe.execute())[0]

        hits = await self.call(count)
        if hits is FAILED or hits <= LIMITS[bucket]:
            return None
        return max(1, int((window + 1) * WINDOW_S - now))


def _bucket(request: Request) -> tuple[str, str] | None:
    """(bucket, subject) for a write, or None if it isn't counted."""
    path = request.url.path
    if path == LOGIN_PATH:
        return "login", request.state.client_ip
    settings = request.app.state.settings
    token = request.cookies.get(COOKIE_NAME)
    claims = (
        verify_session(settings.session_secret, token, settings.session_max_age_s)
        if token
        else None
    )
    if claims is None:
        return None
    if "/scores/" in path and path.endswith("/issue"):
        return "make_issue", claims[0]
    return "write", claims[0]


async def limit_writes(request: Request) -> None:
    """Router-wide dependency on /api/v1 (app/main.py): runs before a route's own
    dependencies, so an over-limit request costs no database work."""
    limiter: RateLimiter = request.app.state.rate_limiter
    if request.method not in WRITES or request.url.path in EXEMPT or not limiter.available():
        return
    counted = _bucket(request)
    if counted is None:
        return
    bucket, subject = counted
    retry_after = await limiter.over_limit(bucket, subject)
    if retry_after is not None:
        raise AppError(
            429,
            "rate_limited",
            f"Too many requests. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
