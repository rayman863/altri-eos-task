"""The clock: APP_NOW parsing, frozen and ticking modes, and the wall-clock ban."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.clock import FrozenClock, TickingClock, clock_from_settings, parse_app_now
from app.config import Settings
from tests.helpers import utc

APP_NOW = utc("2026-11-11T15:00:00Z")


def test_parse_app_now_accepts_z_and_offsets():
    assert parse_app_now("2026-11-11T15:00:00Z") == APP_NOW
    assert parse_app_now("2026-11-11T09:00:00-06:00") == APP_NOW
    assert parse_app_now("2026-11-11T15:00:00Z").tzinfo == UTC


@pytest.mark.parametrize("bad", ["2026-11-11T15:00:00", "yesterday", ""])
def test_parse_app_now_rejects_naive_or_garbage(bad):
    with pytest.raises(ValueError):
        parse_app_now(bad)


def test_frozen_clock_stays_put_and_can_be_moved():
    clock = FrozenClock(APP_NOW)
    assert clock.now() == APP_NOW
    clock.advance(timedelta(days=5))
    assert clock.now() == utc("2026-11-16T15:00:00Z")
    clock.set(APP_NOW)
    assert clock.now() == APP_NOW


def test_ticking_clock_advances_with_the_wall_clock():
    wall = [datetime(2030, 1, 1, 12, 0, tzinfo=UTC)]
    clock = TickingClock(APP_NOW, real_anchor=wall[0], wall=lambda: wall[0])
    assert clock.now() == APP_NOW
    wall[0] += timedelta(minutes=7, seconds=30)
    assert clock.now() == APP_NOW + timedelta(minutes=7, seconds=30)


def test_clock_from_settings_respects_the_mode():
    frozen = clock_from_settings(Settings(app_now="2026-11-11T15:00:00Z", app_clock_mode="frozen"))
    assert isinstance(frozen, FrozenClock)
    assert frozen.now() == APP_NOW
    ticking = clock_from_settings(
        Settings(app_now="2026-11-11T15:00:00Z", app_clock_mode="ticking")
    )
    assert isinstance(ticking, TickingClock)
    assert abs(ticking.now() - APP_NOW) < timedelta(seconds=5)


def test_nothing_but_clock_py_reads_the_wall_clock():
    """Brief 2.7: read now from APP_NOW, not the system clock (plan 3.2)."""
    app_dir = Path(__file__).resolve().parents[2] / "app"
    forbidden = re.compile(r"datetime\.(now|utcnow|today)\(|date\.today\(|time\.time\(")
    offenders = [
        f"{path.relative_to(app_dir.parent)}:{n}"
        for path in app_dir.rglob("*.py")
        if path.name != "clock.py"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if forbidden.search(line)
    ]
    assert offenders == []
