"""The shared business clock (plan 3.2): every process and every restart agree on "now",
so rows stamped with business time never end up "in the future" after a restart."""

import asyncio
from datetime import timedelta

from app.clock import parse_app_now
from app.clock_anchor import anchored_clock, ensure_clock_anchor
from app.db import make_sessionmaker
from app.main import create_app
from tests.api.conftest import CSRF, asgi_request, session_token
from tests.db.conftest import engine_for, query
from tests.helpers import utc

APP_NOW = parse_app_now("2026-11-11T15:00:00Z")
REAL = utc("2027-03-01T08:00:00Z")  # some real time, unrelated to business time


def wall_at(holder: list):
    return lambda: holder[0]


def test_restarts_and_other_workers_reuse_the_anchor(seeded):
    async def scenario():
        engine = engine_for(seeded.database_url)  # eos_app, like the API
        try:
            wall = [REAL]
            first = await anchored_clock(engine, APP_NOW, wall_at(wall))
            wall[0] = REAL + timedelta(minutes=30)
            # A second worker, or the same API after a restart, 30 real minutes later:
            second = await anchored_clock(engine, APP_NOW, wall_at(wall))
            return first.now(), second.now()
        finally:
            await engine.dispose()

    first_now, second_now = asyncio.run(scenario())
    assert first_now == second_now == APP_NOW + timedelta(minutes=30)
    assert query(seeded.owner_database_url, "SELECT count(*) FROM clock_anchor")[0][0] == 1


def test_a_new_app_now_replaces_the_anchor(seeded):
    async def scenario():
        engine = engine_for(seeded.database_url)
        try:
            await ensure_clock_anchor(engine, APP_NOW, lambda: REAL)
            later = REAL + timedelta(days=2)
            moved = APP_NOW + timedelta(days=7)
            anchor = await ensure_clock_anchor(engine, moved, lambda: later)
            clock = await anchored_clock(engine, moved, lambda: later)
            return anchor, clock.now()
        finally:
            await engine.dispose()

    anchor, now = asyncio.run(scenario())
    assert anchor == REAL + timedelta(days=2)
    assert now == APP_NOW + timedelta(days=7)


def test_work_done_before_a_restart_is_still_done_after_it(seeded):
    """The Phase 4 review probe: t12 marked done 30 business minutes in must stay done
    once the API restarts."""

    async def scenario():
        engine = engine_for(seeded.database_url)
        wall = [REAL]
        try:

            async def start_api():
                app = create_app(seeded)
                app.state.engine = engine
                app.state.sessionmaker = make_sessionmaker(engine)
                app.state.clock = await anchored_clock(engine, APP_NOW, wall_at(wall))
                return app

            api = await start_api()
            login = await asgi_request(
                api, "POST", "/api/v1/auth/login", json={"user_id": "u3"}, headers=CSRF
            )
            token = session_token(login)
            wall[0] = REAL + timedelta(minutes=30)
            done = await asgi_request(
                api,
                "PUT",
                "/api/v1/todos/t12/done",
                json={"done": True},
                headers=CSRF,
                cookie=token,
            )
            wall[0] = REAL + timedelta(minutes=31)
            restarted = await start_api()
            todos = await asgi_request(
                restarted, "GET", "/api/v1/teams/team_lead/todos", cookie=token
            )
            return done.body, next(t for t in todos.body["items"] if t["id"] == "t12")
        finally:
            await engine.dispose()

    done, after = asyncio.run(scenario())
    assert done["done_at"] == "2026-11-11T15:30:00Z"
    assert (after["done_at"], after["overdue"]) == ("2026-11-11T15:30:00Z", False)
