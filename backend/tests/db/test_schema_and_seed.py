"""Schema constraints, role triggers, least-privilege roles and the seed (Phase 2 exit
criteria). Runs against eos_test; every probe that should fail runs in a rolled-back
transaction."""

import subprocess

import pytest

from tests.db.conftest import BACKEND, db_error, query, reseed

CHECK, UNIQUE, FOREIGN_KEY, NO_PRIVILEGE = "23514", "23505", "23503", "42501"

EXPECTED_COUNTS = {
    "companies": 1,
    "users": 9,
    "teams": 3,
    "memberships": 11,
    "measurables": 7,
    "scores": 83,
    "rocks": 7,
    "milestones": 12,
    "issues": 9,
    "todos": 20,
    "meetings": 2,
    "meeting_attendees": 10,
    "meeting_ratings": 7,
    "meeting_summaries": 2,
}


def counts(settings) -> dict[str, int]:
    return {
        table: query(settings.owner_database_url, f"SELECT count(*) FROM {table}")[0][0]  # noqa: S608 - fixed table names
        for table in EXPECTED_COUNTS
    }


ISSUE_COLUMNS = "id, team_id, owner_id, title, created_at"
NEW_ISSUE = (
    f"INSERT INTO issues ({ISSUE_COLUMNS}) "  # noqa: S608 - constant column list
    "VALUES ('i_new', :team, :owner, 'Probe', '2026-11-11T15:00:00Z')"
)


# ---- seed ---------------------------------------------------------------------------


def test_seed_loads_everything(seeded):
    assert counts(seeded) == EXPECTED_COUNTS


def test_seed_is_safe_to_rerun(seeded):
    before = counts(seeded)
    inserted = reseed(seeded, reset=False)
    assert all(n == 0 for n in inserted.values()), inserted
    assert counts(seeded) == before


def test_rerunning_the_seed_keeps_edits_made_in_the_app(seeded):
    query(
        seeded.database_url,  # as eos_app, like the API
        "UPDATE scores SET value = 77 WHERE measurable_id = 'm1' AND week_start = '2026-11-02'",
    )
    reseed(seeded, reset=False)
    value = query(
        seeded.owner_database_url,
        "SELECT value FROM scores WHERE measurable_id = 'm1' AND week_start = '2026-11-02'",
    )[0][0]
    assert value == 77


def test_seed_keeps_decimals_exact(seeded):
    value = query(
        seeded.owner_database_url,
        "SELECT value FROM scores WHERE measurable_id = 'm2' AND week_start = '2026-09-07'",
    )[0][0]
    assert str(value.normalize()) == "3"  # 3.0 stored as exact NUMERIC, not a float


def test_seeded_meeting_snapshots(seeded):
    snapshots = dict(
        query(seeded.owner_database_url, "SELECT meeting_id, summary FROM meeting_summaries")
    )
    mt2 = snapshots["mt2"]
    assert mt2["scorecard_week"] == "2026-10-26"
    assert mt2["measurable_status"] == {
        "m1": "off_track",
        "m2": "on_track",
        "m3": "on_track",
        "m4": "off_track",
        "m5": "on_track",
    }
    assert (mt2["issues_solved"], mt2["todos_created"], mt2["rating"]) == (["i6"], ["t30"], 8.3)
    assert mt2["attendee_ids"] == ["u1", "u2", "u3", "u4", "u5"]
    assert mt2["labels"]["issues"] == {"i6": "Payroll runs, week of Oct 26"}
    assert mt2["ended_at"] == "2026-11-04T16:20:00Z"
    mt1 = snapshots["mt1"]
    assert (mt1["scorecard_week"], mt1["rating"], mt1["issues_solved"]) == (
        "2026-10-19",
        8.0,
        ["i7"],
    )


def test_seeded_meetings_are_ended_and_in_conclude(seeded):
    rows = query(
        seeded.owner_database_url,
        "SELECT id, section, section_started_at, scorecard_week::text FROM meetings ORDER BY id",
    )
    assert [tuple(r) for r in rows] == [
        ("mt1", "conclude", None, "2026-10-19"),
        ("mt2", "conclude", None, "2026-10-26"),
    ]


# ---- role triggers --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("owner", "team", "allowed"),
    [
        ("u5", "team_lead", False),  # Observer can't own anything
        ("u6", "team_lead", False),  # Team Member of another team
        ("u3", "team_lead", True),  # Team Member of the team
        ("u1", "team_sales", True),  # Admin owns in any team (decision 5)
    ],
)
def test_owner_must_be_eligible(seeded, owner, team, allowed):
    sqlstate, message = db_error(seeded.database_url, NEW_ISSUE, team=team, owner=owner)
    if allowed:
        assert sqlstate is None, message
    else:
        assert sqlstate == CHECK
        assert "owner_eligible" in message or "not eligible" in message


def test_observer_cannot_facilitate(seeded):
    sqlstate, _ = db_error(
        seeded.database_url,
        "INSERT INTO meetings (id, team_id, facilitator_id, started_at, section, scorecard_week)"
        " VALUES ('mt_x', 'team_lead', 'u5', '2026-11-11T15:00:00Z', 'scorecard', '2026-11-02')",
    )
    assert sqlstate == CHECK


def test_observer_cannot_rate_but_attends(seeded):
    sqlstate, _ = db_error(
        seeded.database_url,
        "INSERT INTO meeting_ratings (meeting_id, user_id, rating) VALUES ('mt1', 'u5', 7)",
    )
    assert sqlstate == CHECK


def test_only_attendees_can_rate(seeded):
    sqlstate, _ = db_error(
        seeded.database_url,
        "INSERT INTO meeting_ratings (meeting_id, user_id, rating) VALUES ('mt1', 'u6', 7)",
    )
    assert sqlstate == FOREIGN_KEY


# ---- constraints ------------------------------------------------------------------------


def test_no_duplicate_open_issue_for_a_measurable_week(seeded):
    # i5 is already open for m1, week of 2026-11-02.
    sqlstate, message = db_error(
        seeded.database_url,
        "INSERT INTO issues (id, team_id, owner_id, title, created_at, source_kind,"
        " source_measurable_id, source_week_start) VALUES ('i_dup', 'team_lead', 'u2',"
        " 'Dup', '2026-11-11T15:00:00Z', 'measurable_week', 'm1', '2026-11-02')",
    )
    assert sqlstate == UNIQUE
    assert "ux_issues_open_measurable_week" in message


def test_new_issue_allowed_once_the_old_one_is_solved(seeded):
    # m4, week of 2026-10-26 only has the solved i6.
    sqlstate, message = db_error(
        seeded.database_url,
        "INSERT INTO issues (id, team_id, owner_id, title, created_at, source_kind,"
        " source_measurable_id, source_week_start) VALUES ('i_again', 'team_lead', 'u3',"
        " 'Again', '2026-11-11T15:00:00Z', 'measurable_week', 'm4', '2026-10-26')",
    )
    assert sqlstate is None, message


def test_one_active_meeting_per_team(seeded):
    insert = (
        "INSERT INTO meetings (id, team_id, facilitator_id, started_at, section, scorecard_week)"
        " VALUES ('{id}', 'team_lead', 'u3', '2026-11-11T15:00:00Z', 'scorecard', '2026-11-02')"
    )
    sqlstate, message = db_error(
        seeded.database_url, insert.format(id="mt_a"), insert.format(id="mt_b")
    )
    assert sqlstate == UNIQUE
    assert "ux_meetings_one_active_per_team" in message


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        ("UPDATE issues SET priority = 6 WHERE id = 'i1'", "ck_issues_priority_range"),
        ("UPDATE issues SET solved_at = now() WHERE id = 'i1'", "ck_issues_solved_consistent"),
        (
            "UPDATE issues SET solved_at = now(), resolution_note = '   ' WHERE id = 'i1'",
            "ck_issues_solved_consistent",
        ),
        ("UPDATE issues SET source_kind = 'rock' WHERE id = 'i1'", "ck_issues_source_consistent"),
        ("UPDATE issues SET title = '  ' WHERE id = 'i1'", "ck_issues_title_valid"),
        (
            "INSERT INTO scores (measurable_id, week_start, value) VALUES ('m1', '2026-11-03', 1)",
            "ck_scores_week_start_monday",
        ),
        (
            "INSERT INTO scores (measurable_id, week_start, value)"
            " VALUES ('m1', '2026-11-09', 2000000000)",
            "ck_scores_value_range",
        ),
        (
            "UPDATE meeting_ratings SET rating = 11 WHERE meeting_id = 'mt1'",
            "ck_meeting_ratings_rating_range",
        ),
        ("UPDATE meetings SET section = 'lunch' WHERE id = 'mt1'", "ck_meetings_section_valid"),
        ("UPDATE users SET role = 'owner' WHERE id = 'u2'", "ck_users_role_valid"),
    ],
)
def test_check_constraints(seeded, statement, constraint):
    sqlstate, message = db_error(seeded.owner_database_url, statement)
    assert sqlstate == CHECK, message
    assert constraint in message


@pytest.mark.parametrize(
    "statement",
    [
        # A To-Do in Sales pointing at a Leadership Issue
        "INSERT INTO todos (id, team_id, owner_id, title, due_date, source_issue_id, created_at)"
        " VALUES ('t_x', 'team_sales', 'u6', 'X', '2026-11-20', 'i1', '2026-11-11T15:00:00Z')",
        # A Sales Issue whose source is a Leadership Measurable (a week with no open Issue,
        # so the unique index can't fire first)
        "INSERT INTO issues (id, team_id, owner_id, title, created_at, source_kind,"
        " source_measurable_id, source_week_start) VALUES ('i_x', 'team_sales', 'u6', 'X',"
        " '2026-11-11T15:00:00Z', 'measurable_week', 'm1', '2026-10-26')",
    ],
)
def test_links_never_cross_teams(seeded, statement):
    sqlstate, _ = db_error(seeded.owner_database_url, statement)
    assert sqlstate == FOREIGN_KEY


# ---- least-privilege roles ---------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE should_fail (i int)",
        "TRUNCATE scores",
        "DELETE FROM alembic_version",
        "DROP TABLE scores",
    ],
)
def test_api_role_cannot_change_the_schema_or_migrations(seeded, statement):
    sqlstate, _ = db_error(seeded.database_url, statement)
    assert sqlstate == NO_PRIVILEGE


def test_readonly_role_can_only_read(seeded):
    assert query(seeded.readonly_database_url, "SELECT count(*) FROM users")[0][0] == 9
    sqlstate, _ = db_error(seeded.readonly_database_url, "UPDATE users SET name = 'x'")
    assert sqlstate == NO_PRIVILEGE


# ---- models and migrations agree --------------------------------------------------------


def test_models_match_migrations(migrated):
    result = subprocess.run(["alembic", "check"], cwd=BACKEND, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
