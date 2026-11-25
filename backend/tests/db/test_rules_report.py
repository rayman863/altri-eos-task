"""The rules report against a real database: the command, its scratch database, and its
agreement with the committed file and the frozen meeting snapshots (Phase 3)."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from app import rules_report
from app.clock import parse_app_now
from tests.db.conftest import BACKEND, query
from tests.helpers import committed_report_path


def generate(settings) -> str:
    report = asyncio.run(
        rules_report.generate(
            settings.owner_database_url, Path(settings.seed_path), parse_app_now(settings.app_now)
        )
    )
    return rules_report.render(report)


def test_report_from_the_database_matches_the_committed_file(migrated):
    assert generate(migrated) == committed_report_path().read_text(encoding="utf-8")


def test_report_meetings_match_the_frozen_snapshots(migrated):
    report = json.loads(generate(migrated))
    snapshots = dict(
        query(migrated.owner_database_url, "SELECT meeting_id, summary FROM meeting_summaries")
    )
    meetings = report["teams"]["team_lead"]["meetings"]
    assert sorted(meetings) == sorted(snapshots)
    for meeting_id, recomputed in meetings.items():
        frozen = {key: snapshots[meeting_id][key] for key in recomputed}
        assert recomputed == frozen, meeting_id


def test_report_ignores_data_added_after_seeding(seeded):
    # The report reseeds its scratch database, so edits there don't leak into it.
    query(
        seeded.owner_database_url,
        "UPDATE scores SET value = 0 WHERE measurable_id = 'm5' AND week_start = '2026-11-09'",
    )
    report = json.loads(generate(seeded))
    assert report["teams"]["team_lead"]["measurable_status"]["m5"]["2026-11-09"] == "on_track"


def test_command_prints_only_json_on_stdout(migrated):
    env = {**os.environ, "REPORT_DATABASE_URL": migrated.owner_database_url}
    result = subprocess.run(
        [sys.executable, "-m", "app.rules_report"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == committed_report_path().read_text(encoding="utf-8")
    assert "rules report printed" in result.stderr  # logs go to stderr


def test_command_at_another_date(migrated):
    env = {
        **os.environ,
        "REPORT_DATABASE_URL": migrated.owner_database_url,
        "APP_NOW": "2026-11-18T15:00:00Z",
    }
    result = subprocess.run(
        [sys.executable, "-m", "app.rules_report"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["now"] == "2026-11-18T15:00:00Z"
    assert max(report["teams"]["team_lead"]["todo_completion"]) == "2026-11-16"


def test_command_refuses_a_database_that_is_not_scratch(migrated):
    # Deliberately a database that doesn't exist: if the guard ever broke, this would fail
    # to connect instead of wiping real data (never point this test at `eos`).
    not_scratch = migrated.owner_database_url.rsplit("/", 1)[0] + "/not_a_scratch_db"
    result = subprocess.run(
        [sys.executable, "-m", "app.rules_report"],
        cwd=BACKEND,
        env={**os.environ, "REPORT_DATABASE_URL": not_scratch},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "scratch database" in result.stderr
    assert result.stdout == ""
