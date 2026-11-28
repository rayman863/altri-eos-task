"""To-Dos: the team list with overdue flags and last week's completion, and done/undone."""

from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.authz import ResourceAccess
from app.cache import RequestCache, Until, next_change
from app.errors import AppError
from app.realtime import team_changed
from app.rules.todos import done_as_of, exists_as_of, is_overdue, todo_completion
from app.rules.types import Todo
from app.rules.weeks import last_closed_week, today
from app.services.common import bump_team, team_state, team_tz


def _todo_query() -> Any:
    source = m.Issue.__table__.alias("source_issue")
    return (
        select(
            m.Todo.id,
            m.Todo.team_id,
            m.Todo.title,
            m.Todo.owner_id,
            m.User.name.label("owner_name"),
            m.Todo.due_date,
            m.Todo.done_at,
            m.Todo.created_at,
            m.Todo.source_issue_id,
            source.c.title.label("source_issue_title"),
        )
        .join(m.User, m.User.id == m.Todo.owner_id)
        .outerjoin(source, source.c.id == m.Todo.source_issue_id)
    )


def _rule(r: Any) -> Todo:
    return Todo(r.id, r.due_date, r.done_at, r.created_at)


def todo_out(r: Any, now: datetime, tz: Any) -> dict[str, Any]:
    rule = _rule(r)
    return {
        "id": r.id,
        "title": r.title,
        "owner": {"id": r.owner_id, "name": r.owner_name},
        "due_date": r.due_date,
        # As of now (decision 33): a To-Do done after now isn't done yet.
        "done_at": r.done_at if done_as_of(rule, now) else None,
        "overdue": is_overdue(rule, today(now, tz), now),
        "source_issue": (
            {"id": r.source_issue_id, "title": r.source_issue_title} if r.source_issue_id else None
        ),
        "created_at": r.created_at,
    }


async def get_todo(session: AsyncSession, todo_id: str, now: datetime) -> dict[str, Any]:
    row = (await session.execute(_todo_query().where(m.Todo.id == todo_id))).one_or_none()
    if row is None:
        raise AppError(404, "not_found", "No such To-Do.")
    return todo_out(row, now, await team_tz(session, row.team_id))


async def list_todos(
    session: AsyncSession, team_id: str, now: datetime, cache: RequestCache | None = None
) -> dict[str, Any]:
    """Cached per team version and company date (overdue flags and last week's rate
    depend on it), until the next To-Do timestamp after now (plan 3.14)."""
    if cache is None:
        return (await _list_todos(session, team_id, now)).value
    version, tz = await team_state(session, team_id)
    return await cache.get_or_set(
        f"team:{team_id}:v{version}:todos:{today(now, tz)}",
        cache.cache.ttl_team,
        lambda: _list_todos(session, team_id, now),
        now,
    )


async def _list_todos(session: AsyncSession, team_id: str, now: datetime) -> Until:
    tz = await team_tz(session, team_id)
    all_rows = list(await session.execute(_todo_query().where(m.Todo.team_id == team_id)))
    until = next_change((t for r in all_rows for t in (r.created_at, r.done_at)), now)
    rows = [r for r in all_rows if exists_as_of(_rule(r), now)]
    open_rows = sorted(
        (r for r in rows if not done_as_of(_rule(r), now)), key=lambda r: (r.due_date, r.id)
    )
    done_rows = sorted(
        (r for r in rows if done_as_of(_rule(r), now)),
        key=lambda r: (r.done_at, r.id),
        reverse=True,  # newest first
    )
    week = last_closed_week(now, tz)
    completion = todo_completion([_rule(r) for r in rows], week, now, tz)
    result = {
        "items": [todo_out(r, now, tz) for r in (*open_rows, *done_rows)],
        "last_closed_week_completion": (
            None
            if completion is None
            else {
                "week_start": week,
                "due": completion.due,
                "done": completion.done,
                "rate_percent": completion.rate_percent,
                "meets_target": completion.meets_target,
            }
        ),
    }
    return Until(result, until)


async def set_done(
    session: AsyncSession, access: ResourceAccess, done: bool, now: datetime
) -> dict[str, Any]:
    """Idempotent: marking a done To-Do done again keeps its original done_at."""
    version = await bump_team(session, access.team_id)
    current = await session.scalar(
        select(m.Todo.done_at).where(m.Todo.id == access.resource_id).with_for_update()
    )
    if done and current is None:
        new_value: datetime | None = now
    elif done:
        new_value = current
    else:
        new_value = None
    if new_value != current:
        await session.execute(
            update(m.Todo).where(m.Todo.id == access.resource_id).values(done_at=new_value)
        )
    await team_changed(session, access.team_id, version, "todos", [access.resource_id])
    return await get_todo(session, access.resource_id, now)
