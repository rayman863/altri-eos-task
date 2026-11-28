"""Issues: list in Issue order, create, change priority, solve, and To-Dos from an Issue."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.authz import CurrentUser, ResourceAccess, TeamAccess
from app.cache import RequestCache, Until, next_change
from app.errors import AppError
from app.preconditions import accepts, stale
from app.realtime import team_changed
from app.rules.issues import issue_order
from app.rules.types import Issue
from app.rules.weeks import today
from app.schemas import IssueOut
from app.services.common import bump_team, is_eligible_owner, new_id, team_state, team_tz

NEW_TODO_DUE_DAYS = 7  # plan 3.5: today in company time + 7 days


def _issue_query() -> Any:
    source_todo = m.Todo.__table__.alias("source_todo")
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
            m.Issue.source_rock_id,
            m.Rock.title.label("rock_title"),
            m.Issue.source_todo_id,
            source_todo.c.title.label("todo_title"),
            func.coalesce(todo_counts.c.n, 0).label("todo_count"),
            m.Issue.version,
        )
        .join(m.User, m.User.id == m.Issue.owner_id)
        .outerjoin(m.Measurable, m.Measurable.id == m.Issue.source_measurable_id)
        .outerjoin(m.Rock, m.Rock.id == m.Issue.source_rock_id)
        .outerjoin(source_todo, source_todo.c.id == m.Issue.source_todo_id)
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
    elif r.source_kind == "rock":
        source = {"kind": "rock", "rock_id": r.source_rock_id, "rock_title": r.rock_title}
    elif r.source_kind == "todo":
        source = {"kind": "todo", "todo_id": r.source_todo_id, "todo_title": r.todo_title}
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
    session: AsyncSession,
    team_id: str,
    status: str,
    now: datetime,
    cache: RequestCache | None = None,
) -> list[dict[str, Any]]:
    """Cached per team version and status (plan 3.14), until the next Issue timestamp after
    now, since "unsolved as of now" changes then."""
    if cache is None:
        return (await _list_issues(session, team_id, status, now)).value
    version, _ = await team_state(session, team_id)
    return await cache.get_or_set(
        f"team:{team_id}:v{version}:issues:{status}",
        cache.cache.ttl_team,
        lambda: _list_issues(session, team_id, status, now),
        now,
    )


async def _list_issues(session: AsyncSession, team_id: str, status: str, now: datetime) -> Until:
    rows = {
        r.id: r for r in await session.execute(_issue_query().where(m.Issue.team_id == team_id))
    }
    until = next_change((t for r in rows.values() for t in (r.created_at, r.solved_at)), now)
    if status == "unsolved":
        # Issue order and "unsolved as of now" come from the rules module.
        order = issue_order(
            (Issue(r.id, r.priority, r.created_at, r.solved_at) for r in rows.values()), now
        )
        return Until([issue_out(rows[i]) for i in order], until)
    solved = [r for r in rows.values() if r.solved_at is not None and r.solved_at <= now]
    solved.sort(key=lambda r: (r.solved_at, r.id), reverse=True)  # newest first
    return Until([issue_out(r) for r in solved], until)


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
    session: AsyncSession,
    access: ResourceAccess,
    priority: int | None,
    expected: frozenset[int] | None = None,
) -> dict[str, Any]:
    """Change the priority. Last save wins, unless the client sent If-Match
    (app/preconditions.py): checked here, under the team lock `_open_issue_for_change` took."""
    version = await _open_issue_for_change(session, access)
    if expected is not None:
        current = await session.scalar(
            select(m.Issue.version).where(m.Issue.id == access.resource_id)
        )
        if not accepts(expected, current or 0):
            issue = IssueOut.model_validate(await get_issue(session, access.resource_id))
            raise stale(issue.model_dump(mode="json"), "Issue")
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


# ---- Make it an Issue from a Rock or a To-Do (bonus 3) --------------------------------------
# The same rules as for a Scorecard cell (plan 3.8, services/scorecard.make_issue): one open
# Issue per source, guaranteed by a partial unique index (ux_issues_open_rock / _todo,
# migration 0003), with the team lock taken first so simultaneous clicks queue. The caller
# takes the lock, loads the source (404) and returns an open Issue if there is one; then
# checks the source qualifies (422); then calls `insert_source_issue`.

_SOURCE_COLUMN = {"rock": m.Issue.source_rock_id, "todo": m.Issue.source_todo_id}


async def open_issue_for(session: AsyncSession, kind: str, source_id: str) -> str | None:
    """The unsolved Issue made from this Rock or To-Do, if any."""
    return await session.scalar(
        select(m.Issue.id).where(
            _SOURCE_COLUMN[kind] == source_id,
            m.Issue.source_kind == kind,
            m.Issue.solved_at.is_(None),
        )
    )


async def open_issue_ids(session: AsyncSession, team_id: str, kind: str) -> dict[str, str]:
    """Source id -> unsolved Issue id, for a team's Rocks or To-Dos (their read models)."""
    column = _SOURCE_COLUMN[kind]
    rows = await session.execute(
        select(column, m.Issue.id).where(
            m.Issue.team_id == team_id,
            m.Issue.source_kind == kind,
            m.Issue.solved_at.is_(None),
        )
    )
    return {source_id: issue_id for source_id, issue_id in rows}


async def insert_source_issue(
    session: AsyncSession,
    access: TeamAccess,
    version: int,
    kind: str,
    source_id: str,
    title: str,
    now: datetime,
) -> tuple[dict[str, Any], bool]:
    """Insert the Issue unless a concurrent request got there first: (issue, created)."""
    inserted = await session.scalar(
        pg_insert(m.Issue)
        .values(
            id=new_id("i"),
            team_id=access.team_id,
            owner_id=access.user.id,  # the clicker owns it
            title=title[:200],
            priority=None,
            created_at=now,
            source_kind=kind,
            **{_SOURCE_COLUMN[kind].key: source_id},
        )
        .on_conflict_do_nothing(
            index_elements=[_SOURCE_COLUMN[kind]],
            index_where=text(f"solved_at IS NULL AND source_kind = '{kind}'"),
        )
        .returning(m.Issue.id)
    )
    if inserted is None:
        winner = await open_issue_for(session, kind, source_id)
        if winner is None:  # the winner was solved in between: let the client retry
            raise AppError(409, "conflict", "The Issue changed while it was created. Try again.")
        return await get_issue(session, winner), False
    await team_changed(session, access.team_id, version, "issues", [inserted])
    return await get_issue(session, inserted), True
