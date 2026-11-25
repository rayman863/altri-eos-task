"""The rules report document (seed README format), built from seed.json with no database.

The committed rules_report.json must equal this pure build at the default APP_NOW, and
tests/db checks that the real command (scratch database) produces the same bytes, so the
JSON path and the database path can't disagree.
"""

import json

import pytest

from app.rules.weeks import DEFAULT_TZ
from app.rules_report import TeamData, build_report, render, require_scratch
from tests.helpers import committed_report_path, utc
from tests.rules.conftest import Seed


def teams_from_seed(seed: Seed) -> dict[str, TeamData]:
    team_ids = set(seed.measurable_team.values()) | set(seed.todos) | set(seed.issues)
    teams = {team_id: TeamData(tz=DEFAULT_TZ) for team_id in team_ids}
    for mid, goal in seed.goals.items():
        teams[seed.measurable_team[mid]].goals[mid] = goal
    for (mid, week), value in seed.scores.items():
        teams[seed.measurable_team[mid]].scores[(mid, week)] = value
    for team_id, todos in seed.todos.items():
        teams[team_id].todos.extend(todos)
    for team_id, issues in seed.issues.items():
        teams[team_id].issues.extend(issues)
    for rid, (team_id, status, milestones) in seed.rocks.items():
        teams[team_id].rocks[rid] = (status, milestones)  # type: ignore[assignment]
    for mid, (team_id, meeting) in seed.meetings.items():
        teams[team_id].meetings[mid] = meeting
    return teams


@pytest.fixture(scope="module")
def report(seed: Seed) -> dict:
    return json.loads(render(build_report(seed.now, teams_from_seed(seed))))


# ---- format -------------------------------------------------------------------------------


def test_top_level_shape(report):
    assert report["now"] == "2026-11-11T15:00:00Z"
    assert sorted(report["teams"]) == ["team_lead", "team_ops", "team_sales"]
    for team in report["teams"].values():
        assert list(team) == [
            "measurable_status",
            "todo_completion",
            "overdue_todos",
            "rocks",
            "issue_order",
            "meetings",
        ]


def test_every_measurable_and_completion_has_all_13_weeks(report):
    for team in report["teams"].values():
        for weeks in team["measurable_status"].values():
            assert len(weeks) == 13
            assert (min(weeks), max(weeks)) == ("2026-08-17", "2026-11-09")
        assert len(team["todo_completion"]) == 13
        assert min(team["todo_completion"]) == "2026-08-17"
    lead = report["teams"]["team_lead"]
    assert sorted(lead["measurable_status"]) == ["m1", "m2", "m3", "m4", "m5"]


def test_weeks_with_nothing_due_are_null(report):
    ops = report["teams"]["team_ops"]["todo_completion"]
    assert ops["2026-10-26"] is None
    assert ops["2026-11-02"] == {"due": 1, "done": 1, "rate_percent": 100, "meets_target": True}


def test_ratings_are_numbers_with_one_decimal(seed):
    text = render(build_report(seed.now, teams_from_seed(seed)))
    assert '"rating": 8.3' in text
    assert '"rating": 8.0' in text


# ---- values (plan section 4 oracles) ------------------------------------------------------


def test_leadership_values(report):
    lead = report["teams"]["team_lead"]
    assert lead["todo_completion"]["2026-11-02"] == {
        "due": 10,
        "done": 9,
        "rate_percent": 90,
        "meets_target": True,
    }
    assert lead["todo_completion"]["2026-10-26"] == {
        "due": 3,
        "done": 2,
        "rate_percent": 67,
        "meets_target": False,
    }
    assert lead["overdue_todos"] == ["t12", "t31"]
    assert lead["rocks"] == {
        "r1": {"status": "on_track", "progress_percent": 33},
        "r2": {"status": "off_track", "progress_percent": 13},
        "r3": {"status": "complete", "progress_percent": 100},
        "r4": {"status": "off_track", "progress_percent": 0},
        "r5": {"status": "on_track", "progress_percent": 0},
    }
    assert lead["issue_order"] == ["i2", "i1", "i5", "i3", "i4"]
    status = lead["measurable_status"]
    assert {mid: weeks["2026-11-09"] for mid, weeks in status.items()} == {
        "m1": "pending",
        "m2": "pending",
        "m3": "pending",
        "m4": "pending",
        "m5": "on_track",
    }
    assert (status["m5"]["2026-10-19"], status["m5"]["2026-11-02"]) == ("off_track", "off_track")


def test_meetings(report):
    meetings = report["teams"]["team_lead"]["meetings"]
    assert sorted(meetings) == ["mt1", "mt2"]
    assert meetings["mt1"] == {
        "scorecard_week": "2026-10-19",
        "measurable_status": {
            "m1": "on_track",
            "m2": "on_track",
            "m3": "on_track",
            "m4": "on_track",
            "m5": "off_track",
        },
        "issues_solved": ["i7"],
        "todos_created": ["t20"],
        "attendee_ids": ["u1", "u2", "u3", "u4", "u5"],
        "rating": 8.0,
    }
    assert meetings["mt2"]["scorecard_week"] == "2026-10-26"
    assert meetings["mt2"]["rating"] == 8.3
    assert report["teams"]["team_sales"]["meetings"] == {}


# ---- other dates (the graders run it at other APP_NOW values) --------------------------


def test_earlier_date_moves_the_window_and_drops_later_meetings(seed):
    now = utc("2026-11-01T15:00:00Z")  # Sunday Nov 1, 09:00 Chicago (CST from today), before mt2
    report = json.loads(render(build_report(now, teams_from_seed(seed))))
    lead = report["teams"]["team_lead"]
    assert max(lead["measurable_status"]["m1"]) == "2026-10-26"
    assert min(lead["measurable_status"]["m1"]) == "2026-08-03"
    assert list(lead["meetings"]) == ["mt1"]
    assert report["now"] == "2026-11-01T15:00:00Z"


def test_later_date_closes_the_week_of_nov_9(seed):
    now = utc("2026-11-18T15:00:00Z")
    lead = build_report(now, teams_from_seed(seed))["teams"]["team_lead"]
    week = "2026-11-09"
    assert lead["measurable_status"]["m1"][week] == "off_track"  # closed, no score
    assert lead["measurable_status"]["m5"][week] == "on_track"  # 520 >= 500
    assert max(lead["measurable_status"]["m1"]) == "2026-11-16"


# ---- the committed file -------------------------------------------------------------------


def test_committed_report_matches_the_pure_build(seed):
    path = committed_report_path()
    assert path.is_file(), f"{path} is missing: regenerate it with `make rules-report`"
    expected = render(build_report(seed.now, teams_from_seed(seed)))
    assert path.read_text(encoding="utf-8") == expected, (
        "rules_report.json is stale: regenerate it with `make rules-report`"
    )


# ---- safety ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://eos_owner:pw@db:5432/eos",
        "postgresql+asyncpg://eos_owner:pw@db:5432/eos_activity",
    ],
)
def test_refuses_to_wipe_a_non_scratch_database(url):
    with pytest.raises(SystemExit, match="scratch database"):
        require_scratch(url)
