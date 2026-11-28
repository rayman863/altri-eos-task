"""Scorecard: the 13-week grid, score edits and Make it an Issue (plan 3.8)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.authz import TeamAccess
from app.cache import RequestCache
from app.errors import AppError
from app.jsonutil import decimal_str
from app.preconditions import accepts, stale
from app.realtime import team_changed
from app.rules.scorecard import measurable_status
from app.rules.types import Goal
from app.rules.weeks import current_week, last_closed_week, week_window
from app.schemas import Cell
from app.services.common import (
    bump_team,
    new_id,
    require_shown_week,
    team_state,
    team_tz,
    user_refs,
    week_label,
)
from app.services.issues import get_issue
from app.services.summaries import goal_from_row

_MEASURABLE_COLUMNS = (
    m.Measurable.id,
    m.Measurable.name,
    m.Measurable.unit,
    m.Measurable.owner_id,
    m.Measurable.goal_type,
    m.Measurable.goal_value,
    m.Measurable.goal_min,
    m.Measurable.goal_max,
)
_OPEN_ISSUE_WHERE = "solved_at IS NULL AND source_kind = 'measurable_week'"


def _goal(row: Any) -> Goal:
    return goal_from_row(row.goal_type, row.goal_value, row.goal_min, row.goal_max)


def goal_out(row: Any) -> dict[str, Any]:
    if row.goal_type == "between":
        return {
            "type": "between",
            "min": decimal_str(row.goal_min),
            "max": decimal_str(row.goal_max),
        }
    return {"type": row.goal_type, "value": decimal_str(row.goal_value)}


def cell_out(
    goal: Goal,
    week: date,
    this_week: date,
    value: Decimal | None,
    version: int | None,
    open_issue_id: str | None,
) -> dict[str, Any]:
    return {
        "week_start": week,
        "value": None if value is None else decimal_str(value),
        "status": measurable_status(goal, value, week, this_week),
        "version": version,
        "open_issue_id": open_issue_id,
    }


async def scorecard(
    session: AsyncSession, team_id: str, now: datetime, cache: RequestCache | None = None
) -> dict[str, Any]:
    """The grid, cached per team version and current week: a week closing turns `pending`
    into `off_track`, so the week is part of the key (plan 3.14)."""
    if cache is None:
        return await _scorecard(session, team_id, now)
    version, tz = await team_state(session, team_id)
    key = f"team:{team_id}:v{version}:scorecard:{current_week(now, tz)}"
    return await cache.get_or_set(
        key, cache.cache.ttl_team, lambda: _scorecard(session, team_id, now)
    )


async def _scorecard(session: AsyncSession, team_id: str, now: datetime) -> dict[str, Any]:
    tz = await team_tz(session, team_id)
    weeks = week_window(now, tz)
    this_week = current_week(now, tz)
    measurables = list(
        await session.execute(
            select(*_MEASURABLE_COLUMNS)
            .where(m.Measurable.team_id == team_id)
            .order_by(m.Measurable.id)
        )
    )
    ids = [r.id for r in measurables]
    owners = await user_refs(session, (r.owner_id for r in measurables))
    scores = {
        (r.measurable_id, r.week_start): (r.value, r.version)
        for r in await session.execute(
            select(m.Score.measurable_id, m.Score.week_start, m.Score.value, m.Score.version).where(
                m.Score.measurable_id.in_(ids), m.Score.week_start.in_(weeks)
            )
        )
    }
    open_issues = {
        (r.source_measurable_id, r.source_week_start): r.id
        for r in await session.execute(
            select(m.Issue.id, m.Issue.source_measurable_id, m.Issue.source_week_start).where(
                m.Issue.team_id == team_id,
                m.Issue.solved_at.is_(None),
                m.Issue.source_kind == "measurable_week",
            )
        )
    }
    rows = []
    for r in measurables:
        goal = _goal(r)
        cells = []
        for week in weeks:
            value, version = scores.get((r.id, week), (None, None))
            cells.append(
                cell_out(goal, week, this_week, value, version, open_issues.get((r.id, week)))
            )
        rows.append(
            {
                "id": r.id,
                "name": r.name,
                "unit": r.unit,
                "owner": owners[r.owner_id],
                "goal": goal_out(r),
                "cells": cells,
            }
        )
    return {
        "weeks": weeks,
        "current_week": this_week,
        "last_closed_week": last_closed_week(now, tz),
        "measurables": rows,
    }


async def _measurable(session: AsyncSession, team_id: str, measurable_id: str) -> Any:
    row = (
        await session.execute(
            select(*_MEASURABLE_COLUMNS).where(
                m.Measurable.id == measurable_id, m.Measurable.team_id == team_id
            )
        )
    ).one_or_none()
    if row is None:
        raise AppError(404, "not_found", "No such Measurable in this team.")
    return row


async def _open_issue_id(session: AsyncSession, measurable_id: str, week: date) -> str | None:
    return await session.scalar(
        select(m.Issue.id).where(
            m.Issue.source_measurable_id == measurable_id,
            m.Issue.source_week_start == week,
            m.Issue.solved_at.is_(None),
            m.Issue.source_kind == "measurable_week",
        )
    )


async def _cell(
    session: AsyncSession, measurable: Any, week: date, now: datetime, tz: Any
) -> dict[str, Any]:
    score = (
        await session.execute(
            select(m.Score.value, m.Score.version).where(
                m.Score.measurable_id == measurable.id, m.Score.week_start == week
            )
        )
    ).one_or_none()
    return cell_out(
        _goal(measurable),
        week,
        current_week(now, tz),
        score.value if score else None,
        score.version if score else None,
        await _open_issue_id(session, measurable.id, week),
    )


async def _require_version(
    session: AsyncSession,
    measurable: Any,
    week: date,
    now: datetime,
    tz: Any,
    expected: frozenset[int] | None,
) -> None:
    """Lost-update check (app/preconditions.py), under the team lock taken by the caller."""
    if expected is None:
        return
    current = await session.scalar(
        select(m.Score.version).where(
            m.Score.measurable_id == measurable.id, m.Score.week_start == week
        )
    )
    if not accepts(expected, current or 0):
        cell = await _cell(session, measurable, week, now, tz)
        raise stale(Cell.model_validate(cell).model_dump(mode="json"), "score")


async def put_score(
    session: AsyncSession,
    access: TeamAccess,
    measurable_id: str,
    week: date,
    value: Decimal,
    now: datetime,
    expected: frozenset[int] | None = None,
) -> dict[str, Any]:
    """Set a score. Last save wins (the brief), unless the client sent If-Match."""
    version = await bump_team(session, access.team_id)
    measurable = await _measurable(session, access.team_id, measurable_id)
    tz = await team_tz(session, access.team_id)
    require_shown_week(week, now, tz)
    await _require_version(session, measurable, week, now, tz, expected)
    statement = insert(m.Score).values(
        measurable_id=measurable_id,
        week_start=week,
        value=value,
        # Never repeats for a cell, even after a clear (migration 0005).
        version=func.nextval("score_version_seq"),
        updated_by=access.user.id,
        updated_at=now,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[m.Score.measurable_id, m.Score.week_start],
            set_={
                "value": statement.excluded.value,
                "version": statement.excluded.version,
                "updated_by": statement.excluded.updated_by,
                "updated_at": statement.excluded.updated_at,
            },
        )
    )
    await team_changed(session, access.team_id, version, "scores", [measurable_id])
    return await _cell(session, measurable, week, now, tz)


async def clear_score(
    session: AsyncSession,
    access: TeamAccess,
    measurable_id: str,
    week: date,
    now: datetime,
    expected: frozenset[int] | None = None,
) -> None:
    version = await bump_team(session, access.team_id)
    measurable = await _measurable(session, access.team_id, measurable_id)
    tz = await team_tz(session, access.team_id)
    require_shown_week(week, now, tz)
    await _require_version(session, measurable, week, now, tz, expected)
    await session.execute(
        delete(m.Score).where(m.Score.measurable_id == measurable_id, m.Score.week_start == week)
    )
    await team_changed(session, access.team_id, version, "scores", [measurable_id])


async def make_issue(
    session: AsyncSession, access: TeamAccess, measurable_id: str, week: date, now: datetime
) -> tuple[dict[str, Any], bool]:
    """Plan 3.8. Returns (issue, created). Concurrent clicks end in exactly one Issue.

    In practice the team-row lock taken by `bump_team` queues concurrent clicks, so a later
    one finds the winner in step 1. The partial unique index is the backstop for any write
    path that doesn't take that lock: step 3's ON CONFLICT then makes the loser read the
    winner's row."""
    version = await bump_team(session, access.team_id)
    measurable = await _measurable(session, access.team_id, measurable_id)
    tz = await team_tz(session, access.team_id)

    # 1. An unsolved Issue for this cell wins, even if the score has changed since, and
    #    even if its week has since left the 13 shown weeks.
    existing = await _open_issue_id(session, measurable_id, week)
    if existing is not None:
        return await get_issue(session, existing), False

    # 2. Otherwise the week must be on the Scorecard and the cell off track right now.
    require_shown_week(week, now, tz)
    cell = await _cell(session, measurable, week, now, tz)
    if cell["status"] != "off_track":
        raise AppError(
            422,
            "cell_not_off_track",
            "Only an off-track cell can become an Issue.",
            {"status": cell["status"]},
        )

    # 3. Insert unless a concurrent request got there first.
    inserted = await session.scalar(
        insert(m.Issue)
        .values(
            id=new_id("i"),
            team_id=access.team_id,
            owner_id=access.user.id,  # the clicker owns it
            title=f"{measurable.name}, week of {week_label(week)}",
            priority=None,
            created_at=now,
            source_kind="measurable_week",
            source_measurable_id=measurable_id,
            source_week_start=week,
        )
        .on_conflict_do_nothing(
            index_elements=[m.Issue.source_measurable_id, m.Issue.source_week_start],
            index_where=text(_OPEN_ISSUE_WHERE),
        )
        .returning(m.Issue.id)
    )
    if inserted is None:
        winner = await _open_issue_id(session, measurable_id, week)
        if winner is None:  # the winner was solved in between: let the client retry
            raise AppError(409, "conflict", "The Issue changed while it was created. Try again.")
        return await get_issue(session, winner), False
    await team_changed(session, access.team_id, version, "issues", [inserted])
    return await get_issue(session, inserted), True
