"""To-Do completion rate and overdue, with their boundary cases."""

from datetime import date

from app.rules.todos import is_overdue, todo_completion
from app.rules.types import Todo
from tests.helpers import utc

NOW = utc("2026-11-11T15:00:00Z")
TODAY = date(2026, 11, 11)
WEEK = date(2026, 11, 2)  # Mon Nov 2 .. Sun Nov 8, ends 2026-11-09T06:00Z


def todo(tid: str, due: str, done: str | None = None, created: str = "2026-10-01T00:00:00Z"):
    return Todo(tid, date.fromisoformat(due), utc(done) if done else None, utc(created))


def test_exactly_90_percent_meets_target():
    todos = [todo(f"t{i}", "2026-11-04", "2026-11-04T18:00:00Z") for i in range(9)]
    todos.append(todo("t9", "2026-11-04"))
    result = todo_completion(todos, WEEK, NOW)
    assert (result.due, result.done, result.rate_percent, result.meets_target) == (10, 9, 90, True)


def test_just_under_90_percent_misses_target_even_if_rounding_says_90():
    # 179/199 = 89.95% -> rounds to 90, but the exact ratio is below target.
    todos = [todo(f"d{i}", "2026-11-04", "2026-11-04T18:00:00Z") for i in range(179)]
    todos += [todo(f"n{i}", "2026-11-04") for i in range(20)]
    result = todo_completion(todos, WEEK, NOW)
    assert result.rate_percent == 90
    assert result.meets_target is False


def test_done_after_its_due_week_counts_as_not_done():
    late = todo("late", "2026-11-08", "2026-11-09T06:01:00Z")  # Mon 00:01 Chicago
    result = todo_completion([late], WEEK, NOW)
    assert (result.due, result.done) == (1, 0)


def test_done_in_the_last_second_of_the_week_counts():
    just_in_time = todo("ok", "2026-11-06", "2026-11-09T05:59:59Z")  # Sun 23:59:59 Chicago
    result = todo_completion([just_in_time], WEEK, NOW)
    assert (result.due, result.done) == (1, 1)


def test_done_before_the_week_started_counts():
    early = todo("early", "2026-11-05", "2026-10-30T12:00:00Z")
    assert todo_completion([early], WEEK, NOW).done == 1


def test_nothing_due_means_no_rate():
    other_week = todo("x", "2026-11-12")
    assert todo_completion([other_week], WEEK, NOW) is None
    assert todo_completion([], WEEK, NOW) is None


def test_due_today_is_not_overdue():
    assert not is_overdue(todo("t", "2026-11-11"), TODAY, NOW)


def test_due_yesterday_and_not_done_is_overdue():
    assert is_overdue(todo("t", "2026-11-10"), TODAY, NOW)


def test_done_is_never_overdue():
    assert not is_overdue(todo("t", "2026-11-01", "2026-11-02T12:00:00Z"), TODAY, NOW)


def test_done_after_now_does_not_count_yet():
    # Seen from an earlier APP_NOW, a later completion hasn't happened yet.
    future_done = todo("t", "2026-11-01", "2026-11-20T12:00:00Z")
    assert is_overdue(future_done, TODAY, NOW)


def test_created_after_now_does_not_exist_yet():
    not_yet = todo("t", "2026-11-04", created="2026-11-20T00:00:00Z")
    assert todo_completion([not_yet], WEEK, NOW) is None
    assert not is_overdue(not_yet, TODAY, NOW)
