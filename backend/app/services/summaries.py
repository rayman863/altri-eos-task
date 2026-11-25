"""Meeting summary snapshots (plan 3.9), built from the database with the pure rules.

Used by the seed (seeded meetings mt1, mt2) and, from Phase 5, when a meeting ends. The
snapshot is frozen at that moment and never recomputed; the rules report recomputes from
data on purpose instead.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app import models as m
from app.jsonutil import to_jsonable
from app.rules.meetings import MeetingInput, build_meeting_summary
from app.rules.types import Goal, Issue, Todo


def goal_from_row(goal_type: str, value: Any, minimum: Any, maximum: Any) -> Goal:
    if goal_type == "between":
        return Goal("between", min=minimum, max=maximum)
    return Goal(goal_type, value=value)  # type: ignore[arg-type]


async def team_timezone(conn: AsyncConnection, team_id: str) -> ZoneInfo:
    name = await conn.scalar(
        select(m.Company.timezone)
        .join(m.Team, m.Team.company_id == m.Company.id)
        .where(m.Team.id == team_id)
    )
    if name is None:
        raise LookupError(f"team {team_id!r} not found")
    return ZoneInfo(name)


async def meeting_snapshot(conn: AsyncConnection, meeting_id: str) -> dict[str, Any]:
    """The frozen summary document for an ended meeting, as plain JSON types."""
    meeting = (
        await conn.execute(
            select(
                m.Meeting.team_id,
                m.Meeting.facilitator_id,
                m.Meeting.started_at,
                m.Meeting.ended_at,
                m.Meeting.scorecard_week,
            ).where(m.Meeting.id == meeting_id)
        )
    ).one_or_none()
    if meeting is None:
        raise LookupError(f"meeting {meeting_id!r} not found")
    if meeting.ended_at is None:
        raise ValueError(f"meeting {meeting_id!r} has not ended")

    team_id = meeting.team_id
    tz = await team_timezone(conn, team_id)
    # The week stored when the meeting started, not a recomputation: one source of truth.
    week: date = meeting.scorecard_week

    measurables = (
        await conn.execute(
            select(
                m.Measurable.id,
                m.Measurable.name,
                m.Measurable.goal_type,
                m.Measurable.goal_value,
                m.Measurable.goal_min,
                m.Measurable.goal_max,
            ).where(m.Measurable.team_id == team_id)
        )
    ).all()
    goals = {
        r.id: goal_from_row(r.goal_type, r.goal_value, r.goal_min, r.goal_max) for r in measurables
    }
    scores: dict[tuple[str, date], Decimal] = {
        (r.measurable_id, r.week_start): r.value
        for r in await conn.execute(
            select(m.Score.measurable_id, m.Score.week_start, m.Score.value).where(
                m.Score.measurable_id.in_(list(goals)), m.Score.week_start == week
            )
        )
    }
    issues = (
        await conn.execute(
            select(
                m.Issue.id, m.Issue.title, m.Issue.priority, m.Issue.created_at, m.Issue.solved_at
            ).where(m.Issue.team_id == team_id)
        )
    ).all()
    todos = (
        await conn.execute(
            select(
                m.Todo.id, m.Todo.title, m.Todo.due_date, m.Todo.done_at, m.Todo.created_at
            ).where(m.Todo.team_id == team_id)
        )
    ).all()
    attendee_ids = list(
        await conn.scalars(
            select(m.MeetingAttendee.user_id).where(m.MeetingAttendee.meeting_id == meeting_id)
        )
    )
    ratings = list(
        await conn.scalars(
            select(m.MeetingRating.rating).where(m.MeetingRating.meeting_id == meeting_id)
        )
    )

    summary = build_meeting_summary(
        MeetingInput(meeting.started_at, meeting.ended_at, attendee_ids, ratings, week),
        goals=goals,
        scores=scores,
        issues=[Issue(r.id, r.priority, r.created_at, r.solved_at) for r in issues],
        todos=[Todo(r.id, r.due_date, r.done_at, r.created_at) for r in todos],
        tz=tz,
    )

    people = set(attendee_ids) | {meeting.facilitator_id}
    user_names = {
        r.id: r.name
        for r in await conn.execute(select(m.User.id, m.User.name).where(m.User.id.in_(people)))
    }
    issue_titles = {r.id: r.title for r in issues}
    todo_titles = {r.id: r.title for r in todos}
    labels = {
        "users": dict(sorted(user_names.items())),
        "measurables": {r.id: r.name for r in sorted(measurables, key=lambda r: r.id)},
        "issues": {i: issue_titles[i] for i in summary["issues_solved"]},
        "todos": {t: todo_titles[t] for t in summary["todos_created"]},
    }
    return to_jsonable(
        {
            "meeting_id": meeting_id,
            "team_id": team_id,
            "facilitator_id": meeting.facilitator_id,
            "started_at": meeting.started_at,
            "ended_at": meeting.ended_at,
            **summary,
            "labels": labels,
        }
    )
