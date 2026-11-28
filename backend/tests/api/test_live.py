"""Live updates over SSE with Postgres NOTIFY fan-out (plan 3.7, API contracts 10).

These run the real path: a write commits, Postgres delivers the NOTIFY to each worker's
LISTEN connection, the worker's hub pushes it into the open stream. "Two workers" are two
app instances with their own hub and listener on the same database.
"""

import asyncio
import json
import os
import time
from typing import Any

from sqlalchemy import text

from app.db import make_sessionmaker
from app.main import create_app
from app.realtime import CLOSE, RESYNC, Event, Hub, Listener, asyncpg_dsn, stream
from tests.api.conftest import CSRF, asgi_request, session_token
from tests.db.conftest import engine_for, query

EVENTS = "/api/v1/teams/team_lead/events"
SCORE = "/api/v1/teams/team_lead/measurables/m1/scores/2026-11-02"


async def run_sql(url: str, sql: str) -> None:
    engine = engine_for(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


def parse_sse(raw: bytes) -> list[tuple[str, int | None, dict[str, Any]]]:
    events = []
    for block in raw.decode().split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if line.startswith(":") or ":" not in line:
                continue
            key, _, value = line.partition(": ")
            fields[key] = value
        if "event" in fields:
            events.append(
                (
                    fields["event"],
                    int(fields["id"]) if "id" in fields else None,
                    json.loads(fields["data"]),
                )
            )
    return events


class Worker:
    """One API worker for a test: the app, its engine and its LISTEN connection."""

    def __init__(self, settings, clock) -> None:
        self.app = create_app(settings)
        self.engine = engine_for(settings.database_url)
        self.app.state.engine = self.engine
        self.app.state.sessionmaker = make_sessionmaker(self.engine)
        self.app.state.clock = clock
        self.listener = Listener(
            asyncpg_dsn(settings.database_url),
            self.app.state.hub,
            "eos-test:listen",
            ping_interval_s=0.2,
        )

    async def __aenter__(self) -> "Worker":
        await self.listener.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.listener.stop()
        await self.engine.dispose()

    async def login(self, user_id: str) -> str:
        resp = await asgi_request(
            self.app, "POST", "/api/v1/auth/login", json={"user_id": user_id}, headers=CSRF
        )
        return session_token(resp)

    async def wait_for_streams(self, count: int) -> None:
        for _ in range(200):
            if self.app.state.hub.stream_count() >= count:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("stream never subscribed")


def open_stream(worker: Worker, token: str, seconds: float, arrivals: list) -> asyncio.Task:
    def record(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            arrivals.append((time.perf_counter(), message["body"]))

    return asyncio.create_task(
        asgi_request(
            worker.app, "GET", EVENTS, cookie=token, disconnect_after=seconds, on_send=record
        )
    )


def test_stream_starts_with_retry_and_a_snapshot(app, login, seeded):
    resp = login("u5").get("/teams/team_lead/events", disconnect_after=0.3)
    assert resp.status == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache, no-transform"
    assert resp.headers["x-accel-buffering"] == "no"
    assert resp.raw.startswith(b"retry: 2000\n\n")
    version = query(
        seeded.owner_database_url, "SELECT cache_version FROM teams WHERE id = 'team_lead'"
    )[0][0]
    assert parse_sse(resp.raw)[0] == (
        "snapshot",
        version,
        {"team_id": "team_lead", "cache_version": version, "active_meeting": None},
    )


def test_a_committed_write_reaches_an_open_stream_in_well_under_a_second(app, seeded):
    async def scenario():
        async with Worker(seeded, app.state.clock) as worker:
            reader, writer = await worker.login("u5"), await worker.login("u3")
            arrivals: list = []
            task = open_stream(worker, reader, 1.5, arrivals)
            await worker.wait_for_streams(1)
            resp = await asgi_request(
                worker.app, "PUT", SCORE, json={"value": 9}, headers=CSRF, cookie=writer
            )
            committed = time.perf_counter()
            stream_resp = await task
            return resp, committed, arrivals, stream_resp

    resp, committed, arrivals, stream_resp = asyncio.run(scenario())
    assert resp.status == 200
    events = parse_sse(stream_resp.raw)
    assert [e[0] for e in events] == ["snapshot", "team.changed"]
    name, event_id, data = events[1]
    assert data == {
        "team_id": "team_lead",
        "entity": "scores",
        "ids": ["m1"],
        "cache_version": event_id,
    }
    assert event_id > events[0][1]  # ids only go up
    arrived = next(t for t, body in arrivals if b"team.changed" in body)
    assert arrived - committed < 1.0


def test_two_workers_see_each_others_meeting(app, seeded):
    """The facilitator's worker and a follower's worker are different processes."""

    async def scenario():
        async with Worker(seeded, app.state.clock) as a, Worker(seeded, app.state.clock) as b:
            facilitator, follower = await a.login("u3"), await b.login("u5")
            arrivals: list = []
            task = open_stream(b, follower, 1.5, arrivals)
            await b.wait_for_streams(1)
            start = await asgi_request(
                a.app,
                "POST",
                "/api/v1/teams/team_lead/meetings",
                json={},
                headers=CSRF,
                cookie=facilitator,
            )
            advanced = await asgi_request(
                a.app,
                "POST",
                f"/api/v1/meetings/{start.body['id']}/advance",
                json={"expected_section": "scorecard"},
                headers=CSRF,
                cookie=facilitator,
            )
            return start, advanced, await task

    start, advanced, follower_stream = asyncio.run(scenario())
    assert (start.status, advanced.status) == (201, 200)
    events = parse_sse(follower_stream.raw)
    states = [data for name, _, data in events if name == "meeting.state"]
    assert [s["section"] for s in states] == ["scorecard", "ids"]
    assert states[-1]["id"] == start.body["id"]


def test_rolled_back_writes_send_nothing(app, seeded):
    async def scenario():
        async with Worker(seeded, app.state.clock) as worker:
            reader, writer = await worker.login("u5"), await worker.login("u3")
            task = open_stream(worker, reader, 0.8, [])
            await worker.wait_for_streams(1)
            bad = await asgi_request(
                worker.app,
                "PUT",
                "/api/v1/teams/team_lead/measurables/m1/scores/2026-11-03",  # not a Monday
                json={"value": 9},
                headers=CSRF,
                cookie=writer,
            )
            return bad, await task

    bad, stream_resp = asyncio.run(scenario())
    assert bad.status == 422
    assert [e[0] for e in parse_sse(stream_resp.raw)] == ["snapshot"]


def test_meeting_end_is_announced(app, seeded):
    async def scenario():
        async with Worker(seeded, app.state.clock) as worker:
            token = await worker.login("u3")
            start = await asgi_request(
                worker.app,
                "POST",
                "/api/v1/teams/team_lead/meetings",
                json={},
                headers=CSRF,
                cookie=token,
            )
            task = open_stream(worker, token, 1.0, [])
            await worker.wait_for_streams(1)
            await asgi_request(
                worker.app,
                "POST",
                f"/api/v1/meetings/{start.body['id']}/end",
                json={},
                headers=CSRF,
                cookie=token,
            )
            return start.body["id"], await task

    meeting_id, stream_resp = asyncio.run(scenario())
    events = parse_sse(stream_resp.raw)
    assert events[0][0] == "snapshot" and events[0][2]["active_meeting"]["id"] == meeting_id
    assert ("meeting.ended", {"meeting_id": meeting_id}) in [(n, d) for n, _, d in events]


def test_listener_reconnects_and_streams_resync(app, seeded):
    """Kill the LISTEN connection: the listener reconnects and every stream resends a
    snapshot, because notifications sent while it was down are lost."""

    async def scenario():
        async with Worker(seeded, app.state.clock) as worker:
            # Listen as eos_owner so the test (also eos_owner) may terminate that backend.
            await worker.listener.stop()
            worker.listener = Listener(
                asyncpg_dsn(seeded.owner_database_url),
                worker.app.state.hub,
                "eos-test:listen-kill",
                ping_interval_s=0.2,
            )
            await worker.listener.start()
            token = await worker.login("u5")
            task = open_stream(worker, token, 2.5, [])
            await worker.wait_for_streams(1)
            await run_sql(
                seeded.owner_database_url,
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                " WHERE application_name = 'eos-test:listen-kill'",
            )
            for _ in range(100):
                if worker.listener.connections >= 2:
                    break
                await asyncio.sleep(0.05)
            connections = worker.listener.connections
            # And it still delivers afterwards.
            writer = await worker.login("u3")
            await asgi_request(
                worker.app, "PUT", SCORE, json={"value": 9}, headers=CSRF, cookie=writer
            )
            return connections, await task

    connections, stream_resp = asyncio.run(scenario())
    assert connections >= 2
    names = [e[0] for e in parse_sse(stream_resp.raw)]
    assert names[:2] == ["snapshot", "snapshot"]  # the resync
    assert "team.changed" in names


# ---- the stream generator and hub on their own ------------------------------------------------


def test_heartbeats_keep_idle_streams_alive():
    async def scenario():
        hub = Hub()

        async def snapshot():
            return Event("snapshot", 1, {})

        chunks = []
        gen = stream(hub, "team_lead", "u1", snapshot, heartbeat_s=0.05)
        async for chunk in gen:
            chunks.append(chunk)
            if len(chunks) == 4:
                break
        await gen.aclose()
        return chunks, hub.stream_count()

    chunks, open_streams = asyncio.run(scenario())
    assert chunks[0] == b"retry: 2000\n\n"
    assert chunks[2].startswith(b": ping") and chunks[3].startswith(b": ping")
    assert open_streams == 0  # closing the stream unsubscribes it


def test_resync_and_close():
    async def scenario():
        hub = Hub()
        snapshots = []

        async def snapshot():
            snapshots.append(1)
            return Event("snapshot", len(snapshots), {})

        gen = stream(hub, "team_lead", "u1", snapshot, heartbeat_s=5)
        chunks = [await gen.__anext__(), await gen.__anext__()]
        hub.broadcast(RESYNC)
        chunks.append(await gen.__anext__())
        hub.broadcast(CLOSE)
        rest = [c async for c in gen]
        return chunks, rest, hub.stream_count()

    chunks, rest, open_streams = asyncio.run(scenario())
    assert chunks[2].startswith(b"event: snapshot\nid: 2")
    assert rest == [] and open_streams == 0


def test_at_most_five_streams_per_user(app, login):
    client = login("u5")
    hub = app.state.hub
    held = [hub.subscribe("team_lead", "u5") for _ in range(5)]
    resp = client.get("/teams/team_lead/events", disconnect_after=0.2)
    assert (resp.status, resp.error, resp.headers.get("retry-after")) == (429, "rate_limited", "5")
    for sub in held:
        hub.unsubscribe(sub)
    assert client.get("/teams/team_lead/events", disconnect_after=0.2).status == 200


def test_logout_ends_the_users_open_streams_on_every_worker(app, seeded):
    """A stream is authorized once at connect, so logout must end it explicitly; the user
    logs out on worker A while their stream is open on worker B."""

    async def scenario():
        async with Worker(seeded, app.state.clock) as a, Worker(seeded, app.state.clock) as b:
            token = await a.login("u5")
            other = await b.login("u3")
            mine = open_stream(b, token, 5.0, [])
            theirs = open_stream(b, other, 1.5, [])
            await b.wait_for_streams(2)
            started = time.perf_counter()
            out = await asgi_request(
                a.app, "POST", "/api/v1/auth/logout", json={}, headers=CSRF, cookie=token
            )
            mine_resp = await mine
            ended_after = time.perf_counter() - started
            return out.status, ended_after, mine_resp, await theirs, b.app.state.hub.stream_count()

    status, ended_after, mine, theirs, left = asyncio.run(scenario())
    assert status == 204
    assert ended_after < 2.0  # ended by the logout, not by the 5 s test disconnect
    assert [e[0] for e in parse_sse(mine.raw)] == ["snapshot"]
    assert theirs.status == 200  # other users' streams carry on until they disconnect
    assert left == 0


def test_healthz_reports_realtime(app, seeded):
    async def scenario():
        bare = await asgi_request(app, "GET", "/healthz")
        async with Worker(seeded, app.state.clock) as worker:
            worker.app.state.listener = worker.listener
            token = await worker.login("u5")
            task = open_stream(worker, token, 0.8, [])
            await worker.wait_for_streams(1)
            live = await asgi_request(worker.app, "GET", "/healthz")
            await task
            return bare.body, live.body

    bare, live = asyncio.run(scenario())
    assert bare["realtime"] == {"listener": "off", "streams": 0}
    assert live["realtime"] == {"listener": "ok", "streams": 1}
    assert live["status"] == "ok"
    assert live["worker"] == os.getpid()  # the worker that answered (several share a port)
