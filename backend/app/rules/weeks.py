"""Weeks, days and quarters in company time (brief 2.6 "Time", plan 3.2).

The only module that does time-zone maths. A week runs Monday 00:00:00 to Sunday
23:59:59 in company time and is named by its Monday. Internally a week is the half-open
UTC range [start, next start), so DST weeks come out at their true length (the week of
2026-10-26 is 169 hours in America/Chicago).
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TZ = ZoneInfo("America/Chicago")
WEEK = timedelta(days=7)
SCORECARD_WEEKS = 13


def _require_aware(ts: datetime) -> None:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"naive datetime not allowed: {ts!r}")


def local_date(ts: datetime, tz: ZoneInfo = DEFAULT_TZ) -> date:
    """Calendar date of an instant in company time."""
    _require_aware(ts)
    return ts.astimezone(tz).date()


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_of(ts: datetime, tz: ZoneInfo = DEFAULT_TZ) -> date:
    """The week (its Monday, company time) an instant falls in."""
    return monday_of(local_date(ts, tz))


def week_start_utc(week_start: date, tz: ZoneInfo = DEFAULT_TZ) -> datetime:
    """Monday 00:00 company time, as a UTC instant."""
    if week_start.weekday() != 0:
        raise ValueError(f"week_start must be a Monday, got {week_start.isoformat()}")
    return datetime.combine(week_start, time.min, tzinfo=tz).astimezone(UTC)


def week_bounds(week_start: date, tz: ZoneInfo = DEFAULT_TZ) -> tuple[datetime, datetime]:
    """Half-open UTC range [start, end) of a week; end is the next Monday 00:00."""
    return week_start_utc(week_start, tz), week_start_utc(week_start + WEEK, tz)


def in_week(day: date, week_start: date) -> bool:
    """Whether a calendar date (e.g. a due date) falls in the week."""
    return week_start <= day < week_start + WEEK


def today(now: datetime, tz: ZoneInfo = DEFAULT_TZ) -> date:
    """ "Today" for overdue and past-due checks: the date of now in company time."""
    return local_date(now, tz)


def current_week(now: datetime, tz: ZoneInfo = DEFAULT_TZ) -> date:
    return week_of(now, tz)


def last_closed_week(now: datetime, tz: ZoneInfo = DEFAULT_TZ) -> date:
    """The full week before the current one."""
    return current_week(now, tz) - WEEK


def week_window(
    now: datetime, tz: ZoneInfo = DEFAULT_TZ, count: int = SCORECARD_WEEKS
) -> list[date]:
    """The scorecard's weeks, oldest first, ending with the current week."""
    current = current_week(now, tz)
    return [current - WEEK * (count - 1 - i) for i in range(count)]


def quarter_of(day: date) -> str:
    """Calendar quarter label, e.g. 2026-Q4."""
    return f"{day.year}-Q{(day.month - 1) // 3 + 1}"
