"""Live updates (plan 3.7, API contracts section 10).

Every team write calls `emit()` inside its transaction: `SELECT pg_notify('eos_events', ..)`
is delivered by Postgres only when that transaction commits, so no client ever hears about
a change that was rolled back, and nothing is sent before the data is readable.

Each API worker runs one `Listener` (a dedicated LISTEN connection outside the pool, with a
reconnect loop) that feeds an in-process `Hub`; the hub fans each event out to that
worker's open SSE streams for the team. A facilitator and a follower on different workers
therefore still see each other's changes.

Events are hints: `team.changed` carries ids and an entity type, and `meeting.state` the
meeting state object, which every receiver (an authorized team reader) can fetch anyway.
"""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import asyncpg
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.jsonutil import dumps

log = logging.getLogger("eos.realtime")

CHANNEL = "eos_events"
NOTIFY_LIMIT = 7900  # Postgres caps NOTIFY payloads at 8000 bytes
RESYNC = "_resync"  # internal: the listener reconnected, so streams resend a snapshot
CLOSE = "_close"  # internal: the worker is shutting down


@dataclass(frozen=True, slots=True)
class Event:
    name: str
    id: int | None
    data: dict[str, Any]


# ---- sending ----------------------------------------------------------------------------


async def emit(
    session: AsyncSession, team_id: str, version: int, name: str, data: dict[str, Any]
) -> None:
    """Queue an event for `team_id`; Postgres delivers it when the transaction commits."""
    payload = dumps({"team_id": team_id, "event": name, "id": version, "data": data})
    if len(payload.encode()) > NOTIFY_LIMIT:
        # Too big for NOTIFY (a very large meeting): send a hint, clients refetch.
        payload = dumps(
            {
                "team_id": team_id,
                "event": "team.changed",
                "id": version,
                "data": changed_data(team_id, version, "meeting", [data.get("id")]),
            }
        )
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"), {"channel": CHANNEL, "payload": payload}
    )


def changed_data(team_id: str, version: int, entity: str, ids: list[Any]) -> dict[str, Any]:
    return {
        "team_id": team_id,
        "entity": entity,
        "ids": [i for i in ids if i],
        "cache_version": version,
    }


async def close_user_streams(session: AsyncSession, user_id: str) -> None:
    """Logout: every worker ends this user's open streams once the transaction commits
    (a stream is authorized only at connect, so it must be told; plan 3.15)."""
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": CHANNEL, "payload": dumps({"close_user": user_id})},
    )


async def team_changed(
    session: AsyncSession, team_id: str, version: int, entity: str, ids: list[str]
) -> None:
    await emit(
        session, team_id, version, "team.changed", changed_data(team_id, version, entity, ids)
    )


# ---- the in-process hub -------------------------------------------------------------------


@dataclass(eq=False)  # identity: each stream is its own subscription (and hashable)
class Subscription:
    team_id: str
    user_id: str
    queue: asyncio.Queue[Event] = field(default_factory=lambda: asyncio.Queue(maxsize=256))


class TooManyStreams(Exception):
    pass


class Hub:
    """Open SSE streams of this worker, by team."""

    def __init__(self, max_streams_per_user: int = 5) -> None:
        self.max_streams_per_user = max_streams_per_user
        self._by_team: dict[str, set[Subscription]] = {}
        self._per_user: dict[str, int] = {}

    def has_room(self, user_id: str) -> bool:
        """Checked before a stream starts (an error after the headers is too late)."""
        return self._per_user.get(user_id, 0) < self.max_streams_per_user

    def subscribe(self, team_id: str, user_id: str) -> Subscription:
        if not self.has_room(user_id):
            raise TooManyStreams
        sub = Subscription(team_id, user_id)
        self._by_team.setdefault(team_id, set()).add(sub)
        self._per_user[user_id] = self._per_user.get(user_id, 0) + 1
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        subs = self._by_team.get(sub.team_id)
        if subs is not None and sub in subs:
            subs.discard(sub)
            self._per_user[sub.user_id] -= 1
            if not subs:
                del self._by_team[sub.team_id]

    def publish(self, team_id: str, event: Event) -> None:
        for sub in list(self._by_team.get(team_id, ())):
            self._offer(sub, event)

    def close_user(self, user_id: str) -> None:
        """End every stream of one user on this worker (after their logout)."""
        for subs in list(self._by_team.values()):
            for sub in list(subs):
                if sub.user_id == user_id:
                    self._offer(sub, Event(CLOSE, None, {}))

    def broadcast(self, name: str) -> None:
        """RESYNC or CLOSE to every stream of this worker."""
        for subs in list(self._by_team.values()):
            for sub in list(subs):
                self._offer(sub, Event(name, None, {}))

    @staticmethod
    def _offer(sub: Subscription, event: Event) -> None:
        try:
            sub.queue.put_nowait(event)
        except asyncio.QueueFull:
            # A stuck client: drop its backlog and make it resync instead of growing forever,
            # but never drop a CLOSE (shutdown, logout): that one must still end the stream.
            closing = event.name == CLOSE
            while not sub.queue.empty():
                closing = sub.queue.get_nowait().name == CLOSE or closing
            sub.queue.put_nowait(Event(CLOSE if closing else RESYNC, None, {}))

    def stream_count(self) -> int:
        return sum(len(s) for s in self._by_team.values())


# ---- the LISTEN connection ----------------------------------------------------------------


def asyncpg_dsn(sqlalchemy_url: str) -> str:
    return (
        make_url(sqlalchemy_url).set(drivername="postgresql").render_as_string(hide_password=False)
    )


class Listener:
    """One dedicated LISTEN connection per worker, reconnecting until stopped (plan 3.12).
    After a reconnect it tells every local stream to resync: notifications sent while it
    was down are lost, so streams resend a fresh snapshot instead."""

    def __init__(
        self,
        dsn: str,
        hub: Hub,
        app_name: str,
        *,
        ping_interval_s: float = 5.0,
        connect: Callable[..., Any] = asyncpg.connect,
    ) -> None:
        self.dsn = dsn
        self.hub = hub
        self.app_name = app_name
        self.ping_interval_s = ping_interval_s
        self._connect = connect
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self.connections = 0  # how many times it has (re)connected; tests read it
        self.connected = False

    async def start(self, wait_s: float = 10.0) -> None:
        self._task = asyncio.create_task(self._run(), name="eos-listener")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._ready.wait(), timeout=wait_s)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    @property
    def status(self) -> str:
        """For /healthz: "ok" while listening, else "reconnecting"."""
        return "ok" if self.connected else "reconnecting"

    def _on_notify(self, _conn: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            message = json.loads(payload)
            if "close_user" in message:
                self.hub.close_user(message["close_user"])
                return
            event = Event(message["event"], message.get("id"), message["data"])
            self.hub.publish(message["team_id"], event)
        except (ValueError, KeyError, TypeError):
            log.warning("ignored a malformed notification", extra={"payload": payload[:200]})

    async def _run(self) -> None:
        delay = 0.5
        while True:
            conn = None
            try:
                conn = await self._connect(
                    self.dsn, server_settings={"application_name": self.app_name}
                )
                await conn.add_listener(CHANNEL, self._on_notify)
                self.connections += 1
                self.connected = True
                # On every connect, not only reconnects: streams can already be open if the
                # first connect came late (start() stops waiting after a while), and any
                # notification sent before this moment never reached them.
                if self.connections > 1:
                    log.warning("listener reconnected; streams resync")
                self.hub.broadcast(RESYNC)
                self._ready.set()
                delay = 0.5
                while True:  # a cheap ping notices a dead connection within seconds
                    await asyncio.sleep(self.ping_interval_s)
                    await conn.execute("SELECT 1")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - any failure means "reconnect"
                self.connected = False
                log.warning(
                    "listener connection lost, retrying",
                    extra={"error": type(exc).__name__, "retry_in_s": delay},
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 5.0)
            finally:
                self.connected = False
                if conn is not None:
                    with contextlib.suppress(Exception):
                        await conn.close()


# ---- SSE formatting -----------------------------------------------------------------------

HEARTBEAT_S = 15.0


def sse(event: Event) -> bytes:
    lines = [f"event: {event.name}"]
    if event.id is not None:
        lines.append(f"id: {event.id}")
    lines.append(f"data: {dumps(event.data)}")
    return ("\n".join(lines) + "\n\n").encode()


async def stream(
    hub: Hub,
    team_id: str,
    user_id: str,
    snapshot: Callable[[], Any],
    *,
    heartbeat_s: float = HEARTBEAT_S,
) -> AsyncIterator[bytes]:
    """The body of one SSE response: retry hint, snapshot, then events and heartbeats.

    It subscribes first and reads the snapshot second, so no event can fall between the
    two (a duplicate hint is harmless). Subscribing here, inside the generator, means a
    client that drops before streaming starts never leaves a subscription behind.
    `snapshot()` is an async callable returning a snapshot Event; it opens a short-lived
    session, so the stream never holds a database connection while it waits.

    Event ids (the team's cache_version) only go up: events queued before a snapshot that
    the snapshot already covers are skipped."""
    try:
        sub = hub.subscribe(team_id, user_id)
    except TooManyStreams:
        # Lost the race against the route's has_room() check: end cleanly, client backs off.
        yield b"retry: 5000\n\n"
        yield sse(Event("error", None, {"code": "rate_limited"}))
        return
    last_id = -1

    async def fresh() -> bytes:
        nonlocal last_id
        event = await snapshot()
        if event.id is not None:
            last_id = max(last_id, event.id)
        return sse(event)

    try:
        yield b"retry: 2000\n\n"
        yield await fresh()
        started = time.monotonic()
        while True:
            try:
                event = await asyncio.wait_for(sub.queue.get(), timeout=heartbeat_s)
            except TimeoutError:
                yield f": ping {int(time.monotonic() - started)}\n\n".encode()
                continue
            if event.name == CLOSE:
                return  # the client's EventSource reconnects, likely to another worker
            if event.name == RESYNC:
                yield await fresh()
                continue
            if event.id is not None:
                if event.id <= last_id:
                    continue  # already covered by the last snapshot (or a duplicate)
                last_id = event.id
            yield sse(event)
    finally:
        hub.unsubscribe(sub)


def on_shutdown_signal(callback: Callable[[], None]) -> Callable[[], None]:
    """Run `callback` as soon as the server gets SIGTERM/SIGINT (plan 3.12 item 8).

    Uvicorn waits for open connections (up to --timeout-graceful-shutdown) before it runs
    the lifespan shutdown, and SSE streams never finish by themselves, so without this every
    restart would hold streams for the whole grace period. The hook wraps the server's own
    handler (it still runs, so the server shuts down as usual) and closes this worker's
    streams right away; browsers' EventSource reconnects, to another worker if one is up.
    Only installed when a server handler exists and we're in the main thread. Returns a
    function that puts the previous handlers back."""
    import signal

    loop = asyncio.get_running_loop()
    previous: dict[int, Any] = {}

    def handler(signum: int, frame: Any) -> None:
        loop.call_soon_threadsafe(callback)
        prior = previous.get(signum)
        if callable(prior):
            prior(signum, frame)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            prior = signal.getsignal(sig)
            if callable(prior):  # a server (Uvicorn) handles it: wrap, don't replace
                previous[sig] = prior
                signal.signal(sig, handler)
        except ValueError:  # not the main thread (e.g. some test runners)
            break

    def restore() -> None:
        for sig, prior in previous.items():
            with contextlib.suppress(ValueError):
                signal.signal(sig, prior)

    return restore
