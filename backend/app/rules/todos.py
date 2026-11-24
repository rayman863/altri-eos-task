"""To-Do rules (brief 2.6): overdue, and the weekly completion rate.

Everything is evaluated as of `now`: a To-Do created, or marked done, after `now` hasn't
happened yet. With the seed's default APP_NOW that changes nothing, but it keeps the
answers sensible when the rules report is run at an earlier date.
"""

from collections.abc import Iterable
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.rules.rounding import percent
from app.rules.types import Completion, Todo
from app.rules.weeks import DEFAULT_TZ, in_week, week_bounds

TARGET_NUMERATOR, TARGET_DENOMINATOR = 9, 10  # 90%


def exists_as_of(todo: Todo, now: datetime) -> bool:
    return todo.created_at is None or todo.created_at <= now


def done_as_of(todo: Todo, now: datetime) -> bool:
    return todo.done_at is not None and todo.done_at <= now


def is_overdue(todo: Todo, today: date, now: datetime) -> bool:
    """Not done, and its due date is before today (a To-Do due today is not overdue)."""
    return exists_as_of(todo, now) and not done_as_of(todo, now) and todo.due_date < today


def todo_completion(
    todos: Iterable[Todo], week_start: date, now: datetime, tz: ZoneInfo = DEFAULT_TZ
) -> Completion | None:
    """To-Dos done by the end of the week / To-Dos due that week. None when nothing was due.

    Done after its due week counts as not done. Meeting the 90% target compares the exact
    ratio, not the rounded percent."""
    _, week_end = week_bounds(week_start, tz)
    due = [t for t in todos if exists_as_of(t, now) and in_week(t.due_date, week_start)]
    if not due:
        return None
    done = sum(
        1
        for t in due
        if done_as_of(t, now) and t.done_at < week_end  # type: ignore[operator]
    )
    return Completion(
        due=len(due),
        done=done,
        rate_percent=percent(done, len(due)),
        meets_target=done * TARGET_DENOMINATOR >= TARGET_NUMERATOR * len(due),
    )
