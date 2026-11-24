"""The app's notion of "now" (brief 2.7: read now from APP_NOW, not the system clock).

This is the only module allowed to read the wall clock; a test enforces that.

- FrozenClock: now == APP_NOW exactly (tests, rules report). Tests can move it.
- TickingClock: starts at APP_NOW and advances in real time, so live meeting timers count.
  now = app_now + (wall clock - real_anchor). Phase 5 stores the anchor pair in the
  `clock_anchor` table so every API worker shares one origin (plan 3.2, 3.13); until then
  the anchor is this process's start.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.config import Settings


class Clock(Protocol):
    def now(self) -> datetime: ...


def parse_app_now(value: str) -> datetime:
    """Parse APP_NOW (ISO 8601 with an offset or Z) into an aware UTC datetime."""
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"APP_NOW is not an ISO 8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"APP_NOW must include a UTC offset or Z: {value!r}")
    return parsed.astimezone(UTC)


def wall_clock() -> datetime:
    return datetime.now(UTC)


class FrozenClock:
    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock needs an aware datetime")
        self._at = at.astimezone(UTC)

    def now(self) -> datetime:
        return self._at

    def advance(self, delta: timedelta) -> None:
        """Move the clock (tests: cross a week boundary, run a meeting timer)."""
        self._at += delta

    def set(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock needs an aware datetime")
        self._at = at.astimezone(UTC)


class TickingClock:
    def __init__(
        self,
        app_now: datetime,
        real_anchor: datetime | None = None,
        wall: Callable[[], datetime] = wall_clock,
    ) -> None:
        self._app_now = app_now.astimezone(UTC)
        self._wall = wall
        self._real_anchor = (real_anchor or wall()).astimezone(UTC)

    def now(self) -> datetime:
        return self._app_now + (self._wall() - self._real_anchor)


def clock_from_settings(settings: Settings) -> Clock:
    app_now = parse_app_now(settings.app_now)
    if settings.app_clock_mode == "frozen":
        return FrozenClock(app_now)
    return TickingClock(app_now)
