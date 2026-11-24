"""Every hand-checked case from plan section 4, computed by the rules from seed.json.

These are the values the rules report will print at the default APP_NOW
(2026-11-11T15:00:00Z), so a failure here means the report would be wrong too.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.rules.issues import issue_order
from app.rules.meetings import build_meeting_summary
from app.rules.rocks import rock_progress, rock_status
from app.rules.scorecard import measurable_status
from app.rules.todos import is_overdue, todo_completion
from app.rules.types import Completion
from app.rules.weeks import current_week, today, week_window


def statuses(seed, measurable_id: str) -> dict[str, str]:
    current = current_week(seed.now)
    return {
        week.isoformat(): measurable_status(
            seed.goals[measurable_id], seed.scores.get((measurable_id, week)), week, current
        )
        for week in week_window(seed.now)
    }


def test_window_is_aug_17_to_nov_9(seed):
    weeks = week_window(seed.now)
    assert (weeks[0], weeks[-1]) == (date(2026, 8, 17), date(2026, 11, 9))


def test_m1_full_row(seed):
    on, off = "on_track", "off_track"
    expected = [on, on, off, on, on, on, on, off, on, on, off, off, "pending"]
    assert list(statuses(seed, "m1").values()) == expected


def test_closed_weeks_without_score_are_off_track(seed):
    m5 = statuses(seed, "m5")
    assert m5["2026-10-19"] == "off_track"
    assert m5["2026-11-02"] == "off_track"


def test_current_week_pending_except_m5(seed):
    for mid in ["m1", "m2", "m3", "m4", "m6", "m7"]:
        assert statuses(seed, mid)["2026-11-09"] == "pending", mid
    assert statuses(seed, "m5")["2026-11-09"] == "on_track"  # 520 >= 500


@pytest.mark.parametrize(
    ("mid", "week"),
    [
        ("m2", "2026-09-07"),  # 3.0, at_most 3.0
        ("m2", "2026-11-02"),  # 3.0
        ("m3", "2026-10-19"),  # 2.0, between 2..4
        ("m3", "2026-08-31"),  # 4
        ("m5", "2026-08-31"),  # 500, at_least 500
        ("m6", "2026-08-31"),  # 50, at_least 50
        ("m1", "2026-09-07"),  # 10, at_least 10
    ],
)
def test_boundaries_are_on_track(seed, mid, week):
    assert statuses(seed, mid)[week] == "on_track"


@pytest.mark.parametrize(
    ("mid", "week"),
    [
        ("m3", "2026-10-12"),  # 4.1
        ("m3", "2026-09-07"),  # 4.5
        ("m3", "2026-09-14"),  # 1.8
        ("m2", "2026-10-05"),  # 3.1
        ("m4", "2026-08-31"),  # 0, exactly 1
        ("m4", "2026-09-21"),  # 2
    ],
)
def test_just_outside_is_off_track(seed, mid, week):
    assert statuses(seed, mid)[week] == "off_track"


def completion(seed, team: str, week: str) -> Completion | None:
    return todo_completion(seed.todos[team], date.fromisoformat(week), seed.now)


def test_leadership_week_nov_2_is_exactly_90_percent(seed):
    # t28 done 05:59Z Mon = Sun 23:59 Chicago (counts); t29 done 06:01Z = Mon 00:01 (doesn't)
    assert completion(seed, "team_lead", "2026-11-02") == Completion(10, 9, 90, True)


def test_leadership_week_oct_26_crosses_dst(seed):
    # t11 done 2026-11-02T05:30Z = Sun Nov 1 23:30 CST: still in its due week
    assert completion(seed, "team_lead", "2026-10-26") == Completion(3, 2, 67, False)


def test_other_completion_weeks(seed):
    assert completion(seed, "team_lead", "2026-09-14") == Completion(2, 2, 100, True)
    assert completion(seed, "team_lead", "2026-10-19") is None  # nothing due
    assert completion(seed, "team_lead", "2026-11-09") == Completion(3, 0, 0, False)
    assert completion(seed, "team_sales", "2026-11-09") == Completion(1, 0, 0, False)
    assert completion(seed, "team_ops", "2026-11-02") == Completion(1, 1, 100, True)


def overdue(seed, team: str) -> list[str]:
    day = today(seed.now)
    return sorted(t.id for t in seed.todos.get(team, []) if is_overdue(t, day, seed.now))


def test_overdue_todos(seed):
    assert overdue(seed, "team_lead") == ["t12", "t31"]  # t30 is due today: not overdue
    assert overdue(seed, "team_sales") == []
    assert overdue(seed, "team_ops") == []


@pytest.mark.parametrize(
    ("rock", "status", "progress"),
    [
        ("r1", "on_track", 33),  # ms2 due today: not past due; 1/3
        ("r2", "off_track", 13),  # ms5 due yesterday; 1/8 = 12.5 -> 13
        ("r3", "complete", 100),  # no milestones, complete
        ("r4", "off_track", 0),  # seeded off track, no milestones
        ("r5", "on_track", 0),
        ("r6", "on_track", 0),
        ("r7", "on_track", 0),
    ],
)
def test_rocks(seed, rock, status, progress):
    _, seeded, milestones = seed.rocks[rock]
    assert rock_status(seeded, milestones, today(seed.now)) == status
    assert rock_progress(seeded, milestones) == progress


def test_issue_order(seed):
    assert issue_order(seed.issues["team_lead"], seed.now) == ["i2", "i1", "i5", "i3", "i4"]
    assert issue_order(seed.issues["team_sales"], seed.now) == ["i8"]
    assert issue_order(seed.issues["team_ops"], seed.now) == ["i9"]


def summary(seed, meeting_id: str) -> dict:
    team, meeting = seed.meetings[meeting_id]
    return build_meeting_summary(
        meeting,
        goals=seed.team_goals(team),
        scores=seed.scores,
        issues=seed.issues[team],
        todos=seed.todos[team],
    )


def test_meeting_mt1(seed):
    assert summary(seed, "mt1") == {
        "scorecard_week": "2026-10-19",
        "measurable_status": {
            "m1": "on_track",
            "m2": "on_track",
            "m3": "on_track",
            "m4": "on_track",
            "m5": "off_track",  # no score that week
        },
        "issues_solved": ["i7"],
        "todos_created": ["t20"],
        "attendee_ids": ["u1", "u2", "u3", "u4", "u5"],
        "rating": Decimal("8.0"),
    }


def test_meeting_mt2(seed):
    assert summary(seed, "mt2") == {
        "scorecard_week": "2026-10-26",
        "measurable_status": {
            "m1": "off_track",
            "m2": "on_track",
            "m3": "on_track",
            "m4": "off_track",
            "m5": "on_track",
        },
        "issues_solved": ["i6"],
        "todos_created": ["t30"],
        "attendee_ids": ["u1", "u2", "u3", "u4", "u5"],
        "rating": Decimal("8.3"),  # 8.25 half up; Observer u5 attended but didn't rate
    }
