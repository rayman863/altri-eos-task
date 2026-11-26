"""The clock: APP_NOW parsing, frozen and ticking modes, and the wall-clock ban."""

import ast
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


# Calls that read the wall clock as business time. Durations (time.monotonic,
# time.perf_counter) and log timestamps (LogRecord.created) are fine anywhere.
_ANY_OWNER = {"now", "utcnow", "time_ns"}  # datetime.now, dt.now (aliased), time.time_ns


def _owner_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr  # datetime.date.today -> "date"
    return None


def _imported_names(tree: ast.AST) -> set[str]:
    """Names a module binds by importing (`import x as clock`, `from datetime import
    datetime as clock`): such a `clock` is not the injected Clock."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
    return names


def _wall_clock_calls(source: str) -> list[int]:
    """Line numbers of wall-clock reads, whatever the import style or alias."""
    tree = ast.parse(source)
    clock_is_imported = "clock" in _imported_names(tree)
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr, owner = node.func.attr, _owner_name(node.func.value)
        if owner == "clock" and not clock_is_imported:
            continue  # the sanctioned API: an injected Clock's now() (app.state.clock.now())
        if (
            attr in _ANY_OWNER
            or (attr == "today" and owner in {"date", "datetime"})
            or (attr == "time" and owner == "time")
        ):
            lines.append(node.lineno)
    return lines


def test_wall_clock_detector_catches_common_forms():
    snippets = [
        "datetime.now(UTC)",
        "datetime.datetime.now()",
        "dt.now(UTC)",  # from datetime import datetime as dt
        "date.today()",
        "time.time()",
        "time.time_ns()",
    ]
    assert all(_wall_clock_calls(s) == [1] for s in snippets)
    assert _wall_clock_calls("time.monotonic()\ntime.perf_counter()\nweeks.today(now)") == []
    # Reading the injected business clock is the point, not a violation.
    assert _wall_clock_calls("request.app.state.clock.now()\nclock.now()") == []
    # ...but a `clock` that is really datetime (or any import) is still caught.
    assert _wall_clock_calls("from datetime import datetime as clock\nclock.now()") == [2]
    assert _wall_clock_calls("import datetime as clock\nclock.datetime.now()") == [2]


def test_nothing_but_clock_py_reads_the_wall_clock():
    """Brief 2.7: read now from APP_NOW, not the system clock (plan 3.2)."""
    app_dir = Path(__file__).resolve().parents[2] / "app"
    offenders = [
        f"{path.relative_to(app_dir.parent)}:{n}"
        for path in app_dir.rglob("*.py")
        if path.name != "clock.py"
        for n in _wall_clock_calls(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
