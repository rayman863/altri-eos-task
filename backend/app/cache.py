"""Cache-aside read layer on Redis (plan 3.14, layer L3).

Postgres stays the only source of truth; Redis may be empty, outdated or down and every
read is still correct:

- **Team read models** (Scorecard, Issues, To-Dos, Rocks, meeting state, past meetings)
  are keyed by the team's `cache_version`, read from Postgres first. Every team write
  bumps it in the same transaction (`services.common.bump_team`), so an entry built
  before a write is never read after it. Nothing is ever deleted; old entries expire
  through their TTL.
- **Reference data** (users and access facts, team members, ended-meeting summaries) can
  only change through the seed, and every seed run replaces the
  database's *generation*, a random token in `eos:<database>:gen` that is part of every
  key. A lost or evicted generation is replaced by a new random one, so old entries can
  never come back.
- **Time:** keys carry the company date or week where the result depends on it, and an
  entry built from rows timestamped after "now" (a seed with an earlier APP_NOW) records
  when it stops being true (`Until`), after which it counts as a miss.
- Keys start with `eos:<database>:`, so the demo, test and E2E databases never share an
  entry, even on one Redis.

Never cached: writes and the reads inside them (an entry for a version that then rolls
back would later be read for different data), authorization decisions (only per-user
facts are, and the policy still runs on every request), clock values (`server_now` is
added per response), the rules report.

Failure handling: every Redis call has a 50 ms budget and no retries; an error is a
miss, logged as a warning, and after 3 failures in a row this worker skips Redis for
30 s (the breaker). On a miss the first request takes a short lock and computes while the
others wait up to 1 s for its entry (the stampede guard), then compute themselves.
"""

import asyncio
import hashlib
import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import redis.asyncio as redis
from fastapi import Depends, Request
from redis.backoff import NoBackoff
from redis.retry import Retry
from sqlalchemy.engine import make_url

from app.config import Settings

log = logging.getLogger("eos.cache")

CALL_TIMEOUT_S = 0.05
BREAKER_FAILURES = 3
BREAKER_OPEN_S = 30.0
LOCK_MS = 2000
WAIT_FOR_OTHERS_S = 1.0
POLL_S = 0.025
MAX_CONNECTIONS = 20  # per worker (plan 3.14)
ACCESS_TTL_S = 300
SUMMARY_TTL_S = 24 * 3600

_FAILED = object()  # a Redis call failed (as opposed to a key that isn't there)
FAILED = _FAILED  # for other users of RedisPool.call (app/ratelimit.py)

# Deletes the stampede lock only if it is still ours (it may have expired and been taken).
_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end"


APP_DIR = Path(__file__).resolve().parent


def code_fingerprint(root: Path = APP_DIR) -> str:
    """A short hash of the app's source. Part of every key, so an API running changed
    code (a new read-model field, say) never reads entries an older build wrote, even if
    nothing reseeded in between."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()[:8]


CODE = code_fingerprint()


def namespace(database_url: str, code: str = CODE) -> str:
    """`eos:<database>:<code>`: the prefix of every key for that database's data, as
    this build of the app computes it."""
    return f"eos:{make_url(database_url).database}:{code}"


def _default(value: Any) -> Any:
    # Exact round trips: the response models parse these back to what the service built.
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise TypeError(f"naive datetime can't be cached: {value!r}")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} can't be cached")


def _encode(value: Any, until: datetime | None) -> bytes:
    return json.dumps({"v": value, "u": until}, default=_default, separators=(",", ":")).encode()


@dataclass(frozen=True, slots=True)
class Until:
    """A computed value that is only true until a moment in business time."""

    value: Any
    until: datetime | None


def next_change(times: Any, now: datetime) -> datetime | None:
    """The earliest of these timestamps that is still after `now` (None if none is)."""
    later = [t for t in times if t is not None and t > now]
    return min(later) if later else None


class RedisPool:
    """A worker's Redis connections with the 50 ms budget and the breaker, shared by the
    cache and the rate limiter (app/ratelimit.py). `call` never raises because of Redis;
    `fallback` says in the warning what happens instead."""

    fallback = "reading from Postgres"

    def __init__(self, url: str | None, client_name: str) -> None:
        self.url = url
        self.client_name = client_name
        self._client: redis.Redis | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._failures = 0
        self._open_until = 0.0

    @property
    def enabled(self) -> bool:
        return self.url is not None

    def available(self) -> bool:
        return self.enabled and time.monotonic() >= self._open_until

    def _redis(self) -> redis.Redis:
        # One pool per event loop: a worker has one loop for its lifetime; tests run a new
        # loop per request, and asyncio connections can't move between loops.
        loop = asyncio.get_running_loop()
        if self._client is None or self._loop is not loop:
            assert self.url is not None
            pool = redis.BlockingConnectionPool.from_url(
                self.url,
                max_connections=MAX_CONNECTIONS,
                timeout=CALL_TIMEOUT_S,  # waiting for a free connection
                socket_timeout=CALL_TIMEOUT_S,
                socket_connect_timeout=CALL_TIMEOUT_S,
                retry=Retry(NoBackoff(), 0),
                client_name=self.client_name,  # CLIENT SETNAME, shown by CLIENT LIST
            )
            self._client = redis.Redis(connection_pool=pool)
            self._loop = loop
        return self._client

    async def call(self, op: Callable[[redis.Redis], Awaitable[Any]]) -> Any:
        """Run one Redis command; `_FAILED` on any error, which also feeds the breaker."""
        try:
            async with asyncio.timeout(CALL_TIMEOUT_S * 2):
                result = await op(self._redis())
        except (redis.RedisError, OSError, TimeoutError) as exc:
            self._failures += 1
            if self._failures >= BREAKER_FAILURES:
                self._failures = 0
                self._open_until = time.monotonic() + BREAKER_OPEN_S
                log.warning(
                    f"redis unavailable, {self.fallback} only for 30 s",
                    extra={"error": type(exc).__name__, "client": self.client_name},
                )
            else:
                log.warning(
                    f"redis call failed, {self.fallback}",
                    extra={"error": type(exc).__name__, "client": self.client_name},
                )
            return _FAILED
        self._failures = 0
        return result

    async def ping(self) -> str:
        """For /healthz: `ok`, `degraded` (Redis unreachable) or `off` (switched off)."""
        if not self.enabled:
            return "off"
        try:
            async with asyncio.timeout(CALL_TIMEOUT_S * 4):
                await self._redis().ping()
        except (redis.RedisError, OSError, TimeoutError):
            return "degraded"
        return "ok"

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            await self._client.connection_pool.disconnect()
            self._client = None


class Cache(RedisPool):
    """One per worker (`app.state.cache`): the cache's Redis pool and the hit and miss
    counters shown on /healthz."""

    def __init__(
        self,
        url: str | None,
        namespace: str,
        client_name: str = "eos-api:cache",
        *,
        ttl_team: int = 600,
        ttl_ref: int = 3600,
    ) -> None:
        super().__init__(url, client_name)
        self.namespace = namespace
        self.ttl_team = ttl_team  # team read models: a new version makes them unreachable
        self.ttl_ref = ttl_ref  # reference data: a new generation does
        self.hits = 0
        self.misses = 0

    @classmethod
    def from_settings(cls, settings: Settings, client_name: str = "eos-api:cache") -> "Cache":
        url = settings.redis_url if settings.cache_enabled else None
        return cls(
            url,
            namespace(settings.database_url),
            client_name,
            ttl_team=settings.cache_ttl_team,
            ttl_ref=settings.cache_ttl_ref,
        )

    async def generation(self) -> str | None:
        """This database's current generation, created if Redis has none (None on error)."""
        key = f"{self.namespace}:gen"
        current = await self.call(lambda r: r.get(key))
        if current is _FAILED:
            return None
        if current is None:  # never seeded on this Redis, restarted, or evicted
            token = secrets.token_hex(8)
            existing = await self.call(lambda r: r.set(key, token, nx=True, get=True))
            if existing is _FAILED:
                return None
            current = existing if existing is not None else token
        return current.decode() if isinstance(current, bytes) else str(current)

    def counters(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}


async def rotate_generation(settings: Settings) -> str:
    """Give the database a new generation, which orphans every reference entry cached for
    it. The seed calls this after it commits (so a reader that sees the new generation
    also sees the new data). Raises if Redis can't be reached."""
    client = redis.Redis.from_url(
        settings.redis_url, socket_timeout=5, socket_connect_timeout=5, client_name="eos-seed"
    )
    token = secrets.token_hex(8)
    try:
        await client.set(f"{namespace(settings.database_url)}:gen", token)
    finally:
        await client.aclose()
    return token


_RANK = {"hit": 0, "bypass": 1, "miss": 2}


class RequestCache:
    """The cache as one request sees it: the generation is read once per request, and the
    outcome goes into the request's log line (`cache: hit | miss | bypass`; a request with
    several lookups shows its worst one)."""

    def __init__(self, cache: Cache, state: dict[str, Any]) -> None:
        self.cache = cache
        self.state = state
        self._generation: str | None = None

    def _note(self, outcome: str, note: bool) -> None:
        previous = self.state.get("cache")
        if note and (previous is None or _RANK[outcome] > _RANK[previous]):
            self.state["cache"] = outcome

    async def _key(self, key: str) -> str | None:
        if self._generation is None:
            self._generation = await self.cache.generation()
        if self._generation is None:
            return None
        return f"{self.cache.namespace}:{self._generation}:{key}"

    def _fresh(self, raw: Any, now: datetime | None) -> tuple[bool, Any]:
        if raw is None or raw is _FAILED:
            return False, None
        try:
            entry = json.loads(raw)
            until = entry["u"]
            if until is not None and (
                now is None or now >= datetime.fromisoformat(until.replace("Z", "+00:00"))
            ):
                return False, None  # true until a moment that has passed
            return True, entry["v"]
        except (ValueError, KeyError, TypeError):
            return False, None  # not ours, or an older format: recompute

    async def get_or_set(
        self,
        key: str,
        ttl: int,
        compute: Callable[[], Awaitable[Any]],
        now: datetime | None = None,
        *,
        note: bool = True,
    ) -> Any:
        """The cached value for `key`, or `compute()` stored under it. `compute` may return
        `Until(value, until)`. Values come back as plain JSON types (dates as ISO
        strings), which the response models parse back. `note=False` keeps the lookup
        out of the request's log line (the access facts every request reads), so the line
        speaks for the data the request asked for."""
        if not self.cache.available() or (full := await self._key(key)) is None:
            self._note("bypass", note)
            return _plain(_value(await compute()))

        raw = await self.cache.call(lambda r: r.get(full))
        if raw is _FAILED:
            self._note("bypass", note)
            return _plain(_value(await compute()))
        fresh, value = self._fresh(raw, now)
        if fresh:
            return self._hit(value, note)

        lock = f"{full}:lock"
        token = secrets.token_hex(8)
        locked = await self.cache.call(lambda r: r.set(lock, token, nx=True, px=LOCK_MS))
        if locked is None:  # someone else is computing it: wait a little for their entry
            deadline = time.monotonic() + WAIT_FOR_OTHERS_S
            while time.monotonic() < deadline:
                await asyncio.sleep(POLL_S)
                got = await self.cache.call(lambda r: r.mget(full, lock))
                if got is _FAILED:
                    break
                fresh, value = self._fresh(got[0], now)
                if fresh:
                    return self._hit(value, note)
                if got[1] is None:  # they finished without an entry (their compute failed)
                    break
        try:
            result = await compute()
            until = result.until if isinstance(result, Until) else None
            value = _value(result)
            if until is None or now is None or until > now:
                payload = _encode(value, until)
                await self.cache.call(lambda r: r.set(full, payload, ex=ttl))
        finally:
            if locked is True:
                await self.cache.call(lambda r: r.eval(_RELEASE, 1, lock, token))
        self.cache.misses += 1
        self._note("miss", note)
        # Every path returns the same plain JSON types as a hit, so callers see one shape
        # whether Redis is up, down or switched off.
        return _plain(value)

    def _hit(self, value: Any, note: bool) -> Any:
        self.cache.hits += 1
        self._note("hit", note)
        return value


def _value(result: Any) -> Any:
    return result.value if isinstance(result, Until) else result


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_default))


def for_request(request: Request) -> RequestCache:
    """The request's cache (one per request, so the generation is read once)."""
    state = request.scope.setdefault("state", {})
    current = state.get("_read_cache")
    if current is None:
        current = RequestCache(request.app.state.cache, state)
        state["_read_cache"] = current
    return current


ReadCache = Annotated[RequestCache, Depends(for_request)]
