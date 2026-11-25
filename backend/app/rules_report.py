"""Rules report: `python -m app.rules_report` (brief 2.6, seed README "Rules report format").

Prints every computed value as JSON for APP_NOW, from a freshly seeded scratch database:
migrate `eos_report`, wipe it, load seed.json, read it back and run the pure rules. The
graders also run it at other dates, so every value is recomputed from data, including the
meeting summaries that the app freezes when a meeting ends (plan 3.9). On a fresh seed the
two agree; a DB test checks that.

Only the JSON goes to stdout (logs go to stderr), so the output can be redirected:

    docker compose --progress quiet run --rm --build rules-report
    docker compose --progress quiet run --rm --build -e APP_NOW=2026-11-18T15:00:00Z rules-report
    make rules-report    # rewrites the committed rules_report.json at the seed's now
"""

import asyncio
import logging
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app import models as m
from app import seed
from app.clock import parse_app_now
from app.config import get_settings
from app.jsonutil import dumps
from app.logging import setup_logging
from app.rules.issues import issue_order
from app.rules.meetings import MeetingInput, build_meeting_summary
from app.rules.rocks import rock_progress, rock_status
from app.rules.scorecard import measurable_status
from app.rules.todos import is_overdue, todo_completion
from app.rules.types import Goal, Issue, Milestone, RockStatus, Todo
from app.rules.weeks import current_week, today, week_window
from app.services.summaries import goal_from_row

log = logging.getLogger("eos.rules_report")

BACKEND = Path(__file__).resolve().parents[1]
APP_NAME = "eos-rules-report"
# The report wipes the database it runs on, so it only accepts scratch databases.
SCRATCH_SUFFIXES = ("_report", "_test")


@dataclass
class TeamData:
    """One team's rows as the pure rules' types."""

    tz: ZoneInfo
    goals: dict[str, Goal] = field(default_factory=dict)
    scores: dict[tuple[str, date], Decimal] = field(default_factory=dict)
    todos: list[Todo] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    # rock id -> (stored status, milestones)
    rocks: dict[str, tuple[RockStatus, list[Milestone]]] = field(default_factory=dict)
    # meetings that have an end time; the report keeps those ended as of now
    meetings: dict[str, MeetingInput] = field(default_factory=dict)


# ---- pure: data in, report out ---------------------------------------------------------


def build_report(now: datetime, teams: Mapping[str, TeamData]) -> dict[str, Any]:
    """The report document, in the seed README's format. Lists of ids are sorted as plain
    strings, except issue_order, which is in Issue order."""
    return {
        "now": now,
        "teams": {team_id: _team_report(now, teams[team_id]) for team_id in sorted(teams)},
    }


def _team_report(now: datetime, team: TeamData) -> dict[str, Any]:
    tz = team.tz
    weeks = week_window(now, tz)  # 13 weeks, oldest first, ending with the current week
    this_week = current_week(now, tz)
    day = today(now, tz)
    return {
        "measurable_status": {
            mid: {
                week.isoformat(): measurable_status(
                    goal, team.scores.get((mid, week)), week, this_week
                )
                for week in weeks
            }
            for mid, goal in sorted(team.goals.items())
        },
        "todo_completion": {
            week.isoformat(): _completion(team.todos, week, now, tz) for week in weeks
        },
        "overdue_todos": sorted(t.id for t in team.todos if is_overdue(t, day, now)),
        "rocks": {
            rid: {
                "status": rock_status(stored, milestones, day),
                "progress_percent": rock_progress(stored, milestones),
            }
            for rid, (stored, milestones) in sorted(team.rocks.items())
        },
        "issue_order": issue_order(team.issues, now),
        "meetings": {
            mid: build_meeting_summary(
                meeting,
                goals=team.goals,
                scores=team.scores,
                issues=team.issues,
                todos=team.todos,
                tz=tz,
            )
            for mid, meeting in sorted(team.meetings.items())
            # Ended as of now (decision 33): at an earlier APP_NOW a later meeting
            # hasn't happened yet.
            if meeting.ended_at <= now
        },
    }


def _completion(todos: list[Todo], week: date, now: datetime, tz: ZoneInfo) -> Any:
    result = todo_completion(todos, week, now, tz)
    if result is None:
        return None  # nothing due that week
    return {
        "due": result.due,
        "done": result.done,
        "rate_percent": result.rate_percent,
        "meets_target": result.meets_target,
    }


# ---- database -> TeamData -----------------------------------------------------------------


async def load_teams(conn: AsyncConnection) -> dict[str, TeamData]:
    teams = {
        r.id: TeamData(tz=ZoneInfo(r.timezone))
        for r in await conn.execute(
            select(m.Team.id, m.Company.timezone).join(m.Company, m.Team.company_id == m.Company.id)
        )
    }

    measurable_team: dict[str, str] = {}
    for r in await conn.execute(
        select(
            m.Measurable.id,
            m.Measurable.team_id,
            m.Measurable.goal_type,
            m.Measurable.goal_value,
            m.Measurable.goal_min,
            m.Measurable.goal_max,
        )
    ):
        measurable_team[r.id] = r.team_id
        teams[r.team_id].goals[r.id] = goal_from_row(
            r.goal_type, r.goal_value, r.goal_min, r.goal_max
        )

    for r in await conn.execute(select(m.Score.measurable_id, m.Score.week_start, m.Score.value)):
        teams[measurable_team[r.measurable_id]].scores[(r.measurable_id, r.week_start)] = r.value

    for r in await conn.execute(
        select(m.Todo.id, m.Todo.team_id, m.Todo.due_date, m.Todo.done_at, m.Todo.created_at)
    ):
        teams[r.team_id].todos.append(Todo(r.id, r.due_date, r.done_at, r.created_at))

    for r in await conn.execute(
        select(m.Issue.id, m.Issue.team_id, m.Issue.priority, m.Issue.created_at, m.Issue.solved_at)
    ):
        teams[r.team_id].issues.append(Issue(r.id, r.priority, r.created_at, r.solved_at))

    milestones: dict[str, list[Milestone]] = {}
    for r in await conn.execute(
        select(
            m.Milestone.id, m.Milestone.rock_id, m.Milestone.due_date, m.Milestone.done
        ).order_by(m.Milestone.id)
    ):
        milestones.setdefault(r.rock_id, []).append(Milestone(r.id, r.due_date, r.done))
    for r in await conn.execute(select(m.Rock.id, m.Rock.team_id, m.Rock.status)):
        teams[r.team_id].rocks[r.id] = (r.status, milestones.get(r.id, []))

    attendees: dict[str, list[str]] = {}
    for r in await conn.execute(select(m.MeetingAttendee.meeting_id, m.MeetingAttendee.user_id)):
        attendees.setdefault(r.meeting_id, []).append(r.user_id)
    ratings: dict[str, list[int]] = {}
    for r in await conn.execute(select(m.MeetingRating.meeting_id, m.MeetingRating.rating)):
        ratings.setdefault(r.meeting_id, []).append(r.rating)
    for r in await conn.execute(
        select(m.Meeting.id, m.Meeting.team_id, m.Meeting.started_at, m.Meeting.ended_at).where(
            m.Meeting.ended_at.is_not(None)
        )
    ):
        teams[r.team_id].meetings[r.id] = MeetingInput(
            r.started_at, r.ended_at, attendees.get(r.id, []), ratings.get(r.id, [])
        )
    return teams


# ---- the command --------------------------------------------------------------------------


def require_scratch(database_url: str) -> None:
    name = make_url(database_url).database or ""
    if not name.endswith(SCRATCH_SUFFIXES):
        raise SystemExit(
            f"refusing to run the rules report on {name!r}: it wipes the database it uses,"
            " so it only runs on a scratch database (*_report or *_test)"
        )


def migrate(database_url: str) -> None:
    """`alembic upgrade head` on the scratch database (sync: Alembic runs its own loop)."""
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


async def generate(database_url: str, seed_path: Path, now: datetime) -> dict[str, Any]:
    """Wipe and seed the scratch database, then compute the report from what it holds."""
    require_scratch(database_url)
    await seed.run(reset=True, seed_path=seed_path, database_url=database_url)
    engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"application_name": APP_NAME}},
    )
    try:
        async with engine.connect() as conn:
            teams = await load_teams(conn)
    finally:
        await engine.dispose()
    return build_report(now, teams)


def render(report: Mapping[str, Any]) -> str:
    return dumps(report, indent=2) + "\n"


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, stream=sys.stderr)
    database_url = settings.report_database_url
    require_scratch(database_url)
    # Always the frozen APP_NOW, whatever APP_CLOCK_MODE says: the report is "as of" it.
    now = parse_app_now(settings.app_now)
    migrate(database_url)
    report = asyncio.run(generate(database_url, Path(settings.seed_path), now))
    sys.stdout.write(render(report))
    sys.stdout.flush()
    log.info("rules report printed", extra={"now": settings.app_now, "teams": len(report["teams"])})


if __name__ == "__main__":
    main()
