"""The live-update hub, stream generator and listener without a database (plan 3.7)."""

import asyncio
from typing import Any

from app.realtime import CLOSE, RESYNC, Event, Hub, Listener, stream


async def _snapshot_at(version: int):
    async def snapshot():
        return Event("snapshot", version, {})

    return snapshot


def test_event_ids_never_go_back_after_a_snapshot():
    async def scenario() -> list[bytes]:
        hub = Hub()
        gen = stream(hub, "team_lead", "u1", await _snapshot_at(10), heartbeat_s=5)
        chunks = [await gen.__anext__()]  # subscribed, retry hint sent
        # Queued between subscribe and the snapshot read: 9 and 10 are already covered.
        for version in (9, 10, 11):
            hub.publish("team_lead", Event("team.changed", version, {"v": version}))
        chunks.append(await gen.__anext__())  # the snapshot (id 10)
        chunks.append(await gen.__anext__())  # next event sent must be 11
        await gen.aclose()
        return chunks

    chunks = asyncio.run(scenario())
    assert chunks[1].startswith(b"event: snapshot\nid: 10")
    assert chunks[2].startswith(b"event: team.changed\nid: 11")


def test_losing_the_stream_cap_race_ends_the_stream_cleanly():
    async def scenario() -> list[bytes]:
        hub = Hub(max_streams_per_user=1)
        hub.subscribe("team_lead", "u1")  # the slot another request just took
        return [c async for c in stream(hub, "team_lead", "u1", await _snapshot_at(1))]

    chunks = asyncio.run(scenario())
    assert chunks == [b"retry: 5000\n\n", b'event: error\ndata: {"code": "rate_limited"}\n\n']


def test_queue_overflow_keeps_a_pending_close():
    async def scenario() -> tuple[list[str], list[str]]:
        hub = Hub()
        sub = hub.subscribe("team_lead", "u1")
        for i in range(sub.queue.maxsize):
            hub.publish("team_lead", Event("team.changed", i, {}))
        hub.broadcast(CLOSE)  # overflows: the backlog goes, CLOSE stays
        after_close = [sub.queue.get_nowait().name for _ in range(sub.queue.qsize())]

        other = hub.subscribe("team_lead", "u2")
        for i in range(other.queue.maxsize - 1):
            hub.publish("team_lead", Event("team.changed", i, {}))
        hub.close_user("u2")  # fills the queue; next event overflows with CLOSE inside
        hub.publish("team_lead", Event("team.changed", 999, {}))
        after_overflow = [other.queue.get_nowait().name for _ in range(other.queue.qsize())]
        return after_close, after_overflow

    after_close, after_overflow = asyncio.run(scenario())
    assert after_close == [CLOSE]
    assert after_overflow == [CLOSE]


def test_close_user_ends_only_that_users_streams():
    async def scenario() -> tuple[int, int]:
        hub = Hub()
        mine = hub.subscribe("team_lead", "u5")
        theirs = hub.subscribe("team_lead", "u3")
        hub.close_user("u5")
        return mine.queue.qsize(), theirs.queue.qsize()

    assert asyncio.run(scenario()) == (1, 0)


class FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    async def add_listener(self, channel: str, callback: Any) -> None:
        self.callback = callback

    async def execute(self, sql: str) -> None:
        await asyncio.sleep(0)

    async def close(self) -> None:
        self.closed = True


def test_a_late_first_connect_still_resyncs_open_streams():
    """start() gives up waiting; streams opened meanwhile must resync on the first connect."""

    async def scenario() -> tuple[list[str], str, str]:
        hub = Hub()
        sub = hub.subscribe("team_lead", "u5")
        attempts = {"n": 0}

        async def connect(dsn: str, **kwargs: Any) -> FakeConnection:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise OSError("no connection slots")
            return FakeConnection()

        listener = Listener("postgresql://x", hub, "test", ping_interval_s=0.05, connect=connect)
        before = listener.status
        await listener.start(wait_s=0.01)  # times out: the first attempt fails
        for _ in range(100):
            if listener.connected:
                break
            await asyncio.sleep(0.02)
        after = listener.status
        await listener.stop()
        return [sub.queue.get_nowait().name for _ in range(sub.queue.qsize())], before, after

    queued, before, after = asyncio.run(scenario())
    assert queued == [RESYNC]
    assert (before, after) == ("reconnecting", "ok")


def test_logout_notifications_close_streams_through_the_listener():
    hub = Hub()

    async def scenario() -> int:
        sub = hub.subscribe("team_lead", "u5")
        listener = Listener("postgresql://x", hub, "test")
        listener._on_notify(None, 0, "eos_events", '{"close_user": "u5"}')
        return sub.queue.qsize() and [sub.queue.get_nowait().name][0] == CLOSE

    assert asyncio.run(scenario()) is True
