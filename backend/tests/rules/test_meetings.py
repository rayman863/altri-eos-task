"""Meeting rating and summary."""

from datetime import date
from decimal import Decimal

import pytest

from app.rules.meetings import (
    MeetingInput,
    build_meeting_summary,
    meeting_rating,
    scorecard_week_for,
)
from app.rules.types import Goal, Issue, Todo
from tests.helpers import utc


def test_rating_is_average_to_one_decimal_half_up():
    assert meeting_rating([8, 9, 8, 8]) == Decimal("8.3")  # 8.25
    assert meeting_rating([8, 9, 7]) == Decimal("8.0")


def test_rating_ignores_people_who_did_not_rate():
    # Attendees without a rating just aren't in the list.
    assert meeting_rating([10]) == Decimal("10.0")


def test_no_ratings_means_no_score():
    assert meeting_rating([]) is None


def test_ratings_outside_1_to_10_are_rejected():
    with pytest.raises(ValueError):
        meeting_rating([0, 5])


def test_scorecard_week_is_the_last_closed_week_at_start():
    assert scorecard_week_for(utc("2026-11-04T15:00:00Z")) == date(2026, 10, 26)
    # Started Monday 00:30 Chicago: the week that just closed is still the one reviewed.
    assert scorecard_week_for(utc("2026-11-09T06:30:00Z")) == date(2026, 11, 2)


def test_summary_attributes_by_time_window_inclusive():
    meeting = MeetingInput(
        started_at=utc("2026-11-04T15:00:00Z"),
        ended_at=utc("2026-11-04T16:00:00Z"),
        attendee_ids=["u3", "u1"],
        ratings=[9],
    )
    issues = [
        Issue("at_start", 1, utc("2026-10-01T00:00:00Z"), utc("2026-11-04T15:00:00Z")),
        Issue("at_end", 1, utc("2026-10-01T00:00:00Z"), utc("2026-11-04T16:00:00Z")),
        Issue("after", 1, utc("2026-10-01T00:00:00Z"), utc("2026-11-04T16:00:01Z")),
        Issue("open", 1, utc("2026-10-01T00:00:00Z")),
    ]
    todos = [
        Todo("during", date(2026, 11, 11), None, utc("2026-11-04T15:30:00Z")),
        Todo("before", date(2026, 11, 11), None, utc("2026-11-04T14:59:59Z")),
    ]
    summary = build_meeting_summary(
        meeting,
        goals={"m1": Goal("at_least", value=Decimal(10))},
        scores={("m1", date(2026, 10, 26)): Decimal(12)},
        issues=issues,
        todos=todos,
    )
    assert summary == {
        "scorecard_week": "2026-10-26",
        "measurable_status": {"m1": "on_track"},
        "issues_solved": ["at_end", "at_start"],
        "todos_created": ["during"],
        "attendee_ids": ["u1", "u3"],
        "rating": Decimal("9.0"),
    }
