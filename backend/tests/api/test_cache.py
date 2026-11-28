"""The Redis read cache (layer L3, plan 3.14), against the real Redis of the test stack.

The whole API suite already runs with the cache on (tests/api/conftest.py), so every API
test checks cached reads too; these tests check the cache's own promises: reads are
served from it, a write or a seed makes old entries unreachable, a logout still works at
once, entries built from future rows expire when that moment comes, Redis being down
changes nothing but speed, and one miss computes once.
"""

import asyncio
import logging
import os
import secrets
import subprocess
import sys
from datetime import datetime, timedelta

import pytest

import app.cache as cache_module
from app.cache import (
    CODE,
    Cache,
    RequestCache,
    Until,
    code_fingerprint,
    namespace,
    rotate_generation,
)
from tests.api.conftest import Client, asgi_request
from tests.db.conftest import query

SCORE = "/teams/team_lead/measurables/m1/scores/2026-11-02"


@pytest.fixture(autouse=True)
def _cache_on(seeded):
    if not seeded.cache_enabled:
        pytest.skip("CACHE_ENABLED=false: the suite runs uncached")


class MovableClock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at


def outcomes(caplog: pytest.LogCaptureFixture) -> list[str | None]:
    return [
        getattr(r, "cache", None)
        for r in caplog.records
        if r.name == "eos.request" and r.getMessage() == "request"
    ]


def counts(app) -> dict[str, int]:
    return app.state.cache.counters()


# ---- served from the cache, and never stale -------------------------------------------------


def test_a_second_read_is_a_hit_and_a_write_makes_it_unreachable(app, login, caplog):
    caplog.set_level(logging.INFO, logger="eos.request")
    u3 = login("u3")
    caplog.clear()
    first = u3.get("/teams/team_lead/scorecard")
    second = u3.get("/teams/team_lead/scorecard")
    assert first.body == second.body
    assert outcomes(caplog) == ["miss", "hit"]  # the grid; access facts stay out of the line

    caplog.clear()
    assert u3.put(SCORE, {"value": "123"}).status == 200  # bumps the team's cache_version
    assert outcomes(caplog) == [None]  # a write reads nothing through the cache
    caplog.clear()
    after = u3.get("/teams/team_lead/scorecard")
    assert outcomes(caplog) == ["miss"]
    m1 = next(r for r in after.body["measurables"] if r["id"] == "m1")
    assert next(c for c in m1["cells"] if c["week_start"] == "2026-11-02")["value"] == "123"


ENDPOINTS = [
    "/auth/users",
    "/me",
    "/teams/team_lead",
    "/teams/team_lead/scorecard",
    "/teams/team_lead/issues",
    "/teams/team_lead/issues?status=solved",
    "/teams/team_lead/todos",
    "/teams/team_lead/rocks",
    "/teams/team_lead/meetings/active",
    "/meetings/mt1",
    "/meetings/mt1/summary",
]


def test_cached_reads_are_identical_to_uncached_ones(app, login):
    """The same bytes whether the cache is off, missing or hit, with an active meeting too."""
    u3 = login("u3")
    assert u3.post("/teams/team_lead/meetings").status == 201
    live = app.state.cache
    app.state.cache = Cache(None, "")
    uncached = {path: u3.get(path) for path in ENDPOINTS}
    app.state.cache = live
    missed = {path: u3.get(path) for path in ENDPOINTS}
    hit = {path: u3.get(path) for path in ENDPOINTS}
    for path in ENDPOINTS:
        assert uncached[path].status == 200, path
        assert missed[path].raw == uncached[path].raw, path
        assert hit[path].raw == uncached[path].raw, path
    assert counts(app)["hits"] >= len(ENDPOINTS)


def test_server_now_is_never_cached(app, login):
    clock = MovableClock(app.state.clock.now())
    app.state.clock = clock
    u3 = login("u3")
    assert u3.post("/teams/team_lead/meetings").status == 201
    first = u3.get("/teams/team_lead/meetings/active").body["meeting"]
    clock.at += timedelta(seconds=42)
    second = u3.get("/teams/team_lead/meetings/active").body["meeting"]  # a hit
    assert first["server_now"] != second["server_now"]
    assert {**first, "server_now": None} == {**second, "server_now": None}


def test_logout_still_ends_a_session_at_once(app, login):
    """Access facts are cached for 5 minutes; the session epoch is read from Postgres."""
    u3 = login("u3")
    assert u3.get("/me").status == 200
    assert u3.get("/me").status == 200  # the facts are cached now
    stale = Client(app, u3.token)
    assert u3.post("/auth/logout").status == 204
    assert stale.get("/me").error == "unauthenticated"


def test_a_seed_orphans_every_reference_entry(app, login, seeded):
    """Reference data only changes through the seed, which replaces the generation."""
    u3 = login("u3")
    assert u3.get("/teams/team_lead").body["name"] == "Leadership"
    # Like a new seed: the data changes outside the app, with no cache_version bump.
    query(seeded.owner_database_url, "UPDATE teams SET name = 'Renamed' WHERE id = 'team_lead'")
    assert u3.get("/teams/team_lead").body["name"] == "Leadership"  # still cached
    asyncio.run(rotate_generation(seeded))  # what `python -m app.seed` does after loading
    assert u3.get("/teams/team_lead").body["name"] == "Renamed"


def test_an_entry_from_future_rows_expires_when_their_moment_comes(app, login, seeded):
    """A seed with an earlier APP_NOW has rows timestamped after now: they appear when the
    ticking clock reaches them, cached or not."""
    clock = MovableClock(app.state.clock.now())
    app.state.clock = clock
    later = clock.at + timedelta(minutes=10)
    query(
        seeded.owner_database_url,
        "INSERT INTO issues (id, team_id, title, owner_id, created_at)"
        " VALUES ('i_future1', 'team_lead', 'Not yet raised', 'u3', :at)",
        at=later,
    )
    asyncio.run(rotate_generation(seeded))  # inserted the way a seed would be
    u3 = login("u3")
    ids = lambda: [i["id"] for i in u3.get("/teams/team_lead/issues").body]  # noqa: E731
    assert "i_future1" not in ids()
    assert "i_future1" not in ids()  # a hit: still before the moment
    clock.at = later
    assert "i_future1" in ids()


def test_keys_carry_the_database_and_the_code_so_nothing_is_shared_by_mistake(seeded, tmp_path):
    """Demo, test and E2E databases share one Redis; so do two builds of the API."""
    assert namespace(seeded.database_url) == f"eos:eos_test:{CODE}"
    assert namespace("postgresql+asyncpg://eos_app:pw@db:5432/eos") == f"eos:eos:{CODE}"
    (tmp_path / "a.py").write_text("FIELDS = ['id']")
    before = code_fingerprint(tmp_path)
    (tmp_path / "a.py").write_text("FIELDS = ['id', 'new_field']")
    assert code_fingerprint(tmp_path) != before  # changed code reads none of the old entries


# ---- Redis trouble only makes reads slower ---------------------------------------------------


def test_redis_down_serves_the_same_data_and_opens_the_breaker(app, login, seeded):
    u3 = login("u3")
    good = u3.get("/teams/team_lead/scorecard")
    app.state.cache = Cache("redis://127.0.0.1:1/0", namespace(seeded.database_url))
    for _ in range(3):
        resp = u3.get("/teams/team_lead/scorecard")
        assert (resp.status, resp.raw) == (200, good.raw)
    assert not app.state.cache.available()  # the breaker skips Redis for a while now


def test_healthz_reports_redis(app):
    ok = asyncio.run(asgi_request(app, "GET", "/healthz"))
    assert (ok.status, ok.body["status"], ok.body["redis"]) == (200, "ok", "ok")
    assert set(ok.body["cache"]) == {"hits", "misses"}
    app.state.cache = Cache("redis://127.0.0.1:1/0", "eos:x")
    down = asyncio.run(asgi_request(app, "GET", "/healthz"))
    assert (down.status, down.body["status"], down.body["redis"]) == (200, "degraded", "degraded")
    app.state.cache = Cache(None, "")
    off = asyncio.run(asgi_request(app, "GET", "/healthz"))
    assert (off.status, off.body["status"], off.body["redis"]) == (200, "ok", "off")


def test_the_seed_stops_when_it_cannot_replace_the_generation(seeded):
    """Otherwise the API could start on reference data cached before this seed."""
    env = {
        **os.environ,
        "DATABASE_URL": seeded.database_url,
        "OWNER_DATABASE_URL": seeded.owner_database_url,
        "REDIS_URL": "redis://127.0.0.1:1/0",
    }
    done = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-m", "app.seed"], env=env, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 1
    assert "could not replace the cache generation" in done.stdout + done.stderr


# ---- the cache itself ------------------------------------------------------------------------


def scratch_cache(seeded) -> Cache:
    """A cache on the real Redis under a namespace of its own."""
    return Cache(seeded.redis_url, f"eos:scratch-{secrets.token_hex(4)}")


def test_one_miss_computes_once_however_many_ask(seeded):
    cache = scratch_cache(seeded)
    calls = 0

    async def compute() -> dict:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.2)
        return {"answer": 42}

    async def main() -> list:
        readers = [RequestCache(cache, {}) for _ in range(10)]
        results = await asyncio.gather(*(r.get_or_set("k", 60, compute) for r in readers))
        await cache.close()
        return results

    assert asyncio.run(main()) == [{"answer": 42}] * 10
    assert calls == 1


def test_until_turns_a_hit_into_a_miss_at_that_moment(seeded):
    cache = scratch_cache(seeded)
    now = datetime.fromisoformat("2026-11-11T15:00:00+00:00")
    calls = 0

    async def compute() -> Until:
        nonlocal calls
        calls += 1
        return Until(calls, now + timedelta(seconds=30))

    async def read(at: datetime) -> int:
        return await RequestCache(cache, {}).get_or_set("k", 60, compute, at)

    async def main() -> list[int]:
        values = [await read(now), await read(now + timedelta(seconds=29))]
        values.append(await read(now + timedelta(seconds=30)))
        await cache.close()
        return values

    assert asyncio.run(main()) == [1, 1, 2]


def test_a_failing_compute_releases_its_lock_and_caches_nothing(seeded):
    cache = scratch_cache(seeded)

    async def boom() -> None:
        raise RuntimeError("database down")

    async def main() -> object:
        with pytest.raises(RuntimeError):
            await RequestCache(cache, {}).get_or_set("k", 60, boom)
        started = asyncio.get_running_loop().time()
        value = await RequestCache(cache, {}).get_or_set("k", 60, lambda: asyncio.sleep(0, "ok"))
        waited = asyncio.get_running_loop().time() - started
        await cache.close()
        return value, waited

    value, waited = asyncio.run(main())
    assert value == "ok"
    assert waited < 0.5  # no wait on a lock left behind


def test_a_lock_that_expired_and_was_taken_is_not_released_by_its_first_owner(seeded, monkeypatch):
    monkeypatch.setattr(cache_module, "LOCK_MS", 100)
    cache = scratch_cache(seeded)

    async def main() -> bytes | None:
        reader = RequestCache(cache, {})
        lock = f"{await reader._key('k')}:lock"

        async def slow() -> str:
            await asyncio.sleep(0.25)  # outlives its 100 ms lock...
            await cache.call(lambda r: r.set(lock, b"theirs"))  # ...which someone else took
            return "v"

        await reader.get_or_set("k", 60, slow)
        left = await cache.call(lambda r: r.get(lock))
        await cache.close()
        return left

    assert asyncio.run(main()) == b"theirs"


def test_waiters_stop_waiting_as_soon_as_the_computing_request_fails(seeded):
    cache = scratch_cache(seeded)

    async def boom() -> None:
        await asyncio.sleep(0.1)
        raise RuntimeError("database down")

    async def waiter() -> tuple[str, float]:
        await asyncio.sleep(0.02)  # after the first request took the lock
        started = asyncio.get_running_loop().time()
        value = await RequestCache(cache, {}).get_or_set("k", 60, lambda: asyncio.sleep(0, "ok"))
        return value, asyncio.get_running_loop().time() - started

    async def main() -> list:
        results = await asyncio.gather(
            RequestCache(cache, {}).get_or_set("k", 60, boom), waiter(), return_exceptions=True
        )
        await cache.close()
        return results

    failed, (value, waited) = asyncio.run(main())
    assert isinstance(failed, RuntimeError)
    assert value == "ok"
    assert waited < 0.5  # not the full 1 s wait for an entry that will never come
