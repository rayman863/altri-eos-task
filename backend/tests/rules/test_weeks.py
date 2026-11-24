"""Weeks in company time (America/Chicago), including the DST change on 2026-11-01."""

from datetime import date, datetime, timedelta

import pytest

from app.rules.weeks import (
    current_week,
    in_week,
    last_closed_week,
    local_date,
    quarter_of,
    today,
    week_bounds,
    week_of,
    week_window,
)
from tests.helpers import utc

NOW = utc("2026-11-11T15:00:00Z")  # Wednesday 09:00 in Chicago


def test_now_is_wednesday_of_week_2026_11_09():
    assert current_week(NOW) == date(2026, 11, 9)
    assert last_closed_week(NOW) == date(2026, 11, 2)
    assert today(NOW) == date(2026, 11, 11)


def test_last_second_of_sunday_is_still_the_old_week():
    # Sunday 2026-11-08 23:59:59 CST == 2026-11-09 05:59:59Z
    assert week_of(utc("2026-11-09T05:59:59Z")) == date(2026, 11, 2)


def test_monday_midnight_starts_the_new_week():
    # Monday 2026-11-09 00:00:00 CST == 06:00Z
    assert week_of(utc("2026-11-09T06:00:00Z")) == date(2026, 11, 9)


def test_utc_date_and_company_date_differ_before_6am_utc():
    # 05:30Z on Nov 2 is 23:30 on Sunday Nov 1 in Chicago
    assert local_date(utc("2026-11-02T05:30:00Z")) == date(2026, 11, 1)
    assert week_of(utc("2026-11-02T05:30:00Z")) == date(2026, 10, 26)


def test_dst_week_is_169_hours_long():
    start, end = week_bounds(date(2026, 10, 26))
    assert start == utc("2026-10-26T05:00:00Z")  # CDT, UTC-5
    assert end == utc("2026-11-02T06:00:00Z")  # CST, UTC-6
    assert end - start == timedelta(hours=169)


def test_normal_week_is_168_hours_long():
    start, end = week_bounds(date(2026, 11, 2))
    assert end - start == timedelta(hours=168)


def test_week_bounds_reject_non_monday():
    with pytest.raises(ValueError, match="Monday"):
        week_bounds(date(2026, 11, 3))


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError, match="naive"):
        week_of(datetime(2026, 11, 11, 15, 0))  # noqa: DTZ001 - deliberately naive


def test_window_is_13_weeks_ending_with_the_current_week():
    window = week_window(NOW)
    assert len(window) == 13
    assert window[0] == date(2026, 8, 17)
    assert window[-1] == date(2026, 11, 9)
    assert all(b - a == timedelta(days=7) for a, b in zip(window, window[1:], strict=False))


def test_in_week_covers_monday_to_sunday():
    monday = date(2026, 11, 2)
    assert in_week(date(2026, 11, 2), monday)
    assert in_week(date(2026, 11, 8), monday)
    assert not in_week(date(2026, 11, 9), monday)
    assert not in_week(date(2026, 11, 1), monday)


@pytest.mark.parametrize(
    ("day", "label"),
    [
        (date(2026, 1, 1), "2026-Q1"),
        (date(2026, 3, 31), "2026-Q1"),
        (date(2026, 4, 1), "2026-Q2"),
        (date(2026, 10, 1), "2026-Q4"),
        (date(2026, 12, 31), "2026-Q4"),
    ],
)
def test_quarter_of(day, label):
    assert quarter_of(day) == label
