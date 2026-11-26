"""Issues: list in Issue order, create, change priority, solve, and To-Dos from an Issue."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.authz import CurrentUser, ResourceAccess, TeamAccess
from app.errors import AppError
from app.realtime import team_changed
from app.rules.issues import issue_order
from app.rules.types import Issue
from app.rules.weeks import today
from app.services.common import bump_team, is_eligible_owner, new_id, team_tz

NEW_TODO_DUE_DAYS = 7  # plan 3.5: today in company time + 7 days


def _issue_query() -> Any:
    todo_counts = (
        select(m.Todo.source_issue_id, func.count().label("n"))
        .where(m.Todo.source_issue_id.is_not(None))
        .group_by(m.Todo.source_issue_id)
        .subquery()
    )
    return (
        select(
            m.Issue.id,
            m.Issue.team_id,
            m.Issue.title,
            m.Issue.owner_id,
            m.User.name.label("owner_name"),
            m.Issue.priority,
            m.Issue.created_at,
            m.Issue.solved_at,
            m.Issue.resolution_note,
            m.Issue.source_kind,
            m.Issue.source_measurable_id,
            m.Measurable.name.label("measurable_name"),
            m.Issue.source_week_start,
            func.coalesce(todo_counts.c.n, 0).label("todo_count"),
            m.Issue.version,
        )
        .join(m.User, m.User.id == m.Issue.owner_id)
        .outerjoin(m.Measurable, m.Measurable.id == m.Issue.source_measurable_id)
        .outerjoin(todo_counts, todo_counts.c.source_issue_id == m.Issue.id)
    )


def issue_out(r: Any) -> dict[str, Any]:
    source = None
    if r.source_kind == "measurable_week":
        source = {
            "kind": "measurable_week",
            "measurable_id": r.source_measurable_id,
            "measurable_name": r.measurable_name,
            "week_start": r.source_week_start,
        }
    return {
        "id": r.id,
        "title": r.title,
        "owner": {"id": r.owner_id, "name": r.owner_name},
        "priority": r.priority,
        "created_at": r.created_at,
        "solved_at": r.solved_at,
        "resolution_note": r.resolution_note,
        "source": source,
        "todo_count": r.todo_count,
        "version": r.version,
    }


async def get_issue(session: AsyncSession, issue_id: str) -> dict[str, Any]:
    row = (await session.execute(_issue_query().where(m.Issue.id == issue_id))).one_or_none()
    if row is None:
        raise AppError(404, "not_found", "No such Issue.")
    return issue_out(row)


async def list_issues(
    session: AsyncSession, team_id: str, status: str, now: datetime
) -> list[dict[str, Any]]:
    rows = {
        r.id: r for r in await session.execute(_issue_query().where(m.Issue.team_id == team_id))
    }
    if status == "unsolved":
        # Issue order and "unsolved as of now" come from the rules module.
        order = issue_order(
            (Issue(r.id, r.priority, r.created_at, r.solved_at) for r in rows.values()), now
        )
        return [issue_out(rows[i]) for i in order]
    solved = [r for r in rows.values() if r.solved_at is not None and r.solved_at <= now]
    solved.sort(key=lambda r: (r.solved_at, r.id), reverse=True)  # newest first
    return [issue_out(r) for r in solved]


async def create_issue(
    session: AsyncSession, access: TeamAccess, title: str, priority: int | None, now: datetime
) -> dict[str, Any]:
    version = await bump_team(session, access.team_id)
    issue_id = new_id("i")
    await session.execute(
        insert(m.Issue).values(
            id=issue_id,
            team_id=access.team_id,
            owner_id=access.user.id,  # the caller can write here, so is an eligible owner
            title=title,
            priority=priority,
            created_at=now,
        )
    )
    await team_changed(session, access.team_id, version, "issues", [issue_id])
    return await get_issue(session, issue_id)


async def _open_issue_for_change(session: AsyncSession, access: ResourceAccess) -> int:
    version = await bump_team(session, access.team_id)
    solved_at = await session.scalar(
        select(m.Issue.solved_at).where(m.Issue.id == access.resource_id).with_for_update()
    )
    if solved_at is not None:
        raise AppError(409, "already_solved", "This Issue is already solved.")
    return version


async def set_priority(
    session: AsyncSession, access: ResourceAccess, priority: int | None
) -> dict[str, Any]:
    version = await _open_issue_for_change(session, access)
    await session.execute(
        update(m.Issue)
        .where(m.Issue.id == access.resource_id)
        .values(priority=priority, version=m.Issue.version + 1)
    )
    await team_changed(session, access.team_id, version, "issues", [access.resource_id])
    return await get_issue(session, access.resource_id)


async def solve(
    session: AsyncSession, access: ResourceAccess, note: str, now: datetime
) -> dict[str, Any]:
    version = await _open_issue_for_change(session, access)
    await session.execute(
        update(m.Issue)
        .where(m.Issue.id == access.resource_id)
        .values(
            solved_at=now,
            resolution_note=note,
            solved_by=access.user.id,
            version=m.Issue.version + 1,
        )
    )
    await team_changed(session, access.team_id, version, "issues", [access.resource_id])
    return await get_issue(session, access.resource_id)


async def add_todo(
    session: AsyncSession,
    access: ResourceAccess,
    user: CurrentUser,
    title: str,
    owner_id: str,
    now: datetime,
) -> str:
    """A follow-up To-Do from an Issue (solved or not). Returns the new To-Do id."""
    version = await bump_team(session, access.team_id)
    if not await is_eligible_owner(session, owner_id, access.team_id):
        raise AppError(
            422,
            "owner_not_eligible",
            "The owner must be an Admin or a Team Member of this team.",
        )
    tz = await team_tz(session, access.team_id)
    todo_id = new_id("t")
    await session.execute(
        insert(m.Todo).values(
            id=todo_id,
            team_id=access.team_id,
            owner_id=owner_id,
            title=title,
            due_date=today(now, tz) + timedelta(days=NEW_TODO_DUE_DAYS),
            source_issue_id=access.resource_id,
            created_at=now,
        )
    )
    await team_changed(session, access.team_id, version, "todos", [todo_id])
    return todo_id
