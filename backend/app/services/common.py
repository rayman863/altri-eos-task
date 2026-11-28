"""Helpers shared by the API services."""

import secrets
import string
from collections.abc import Iterable
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.errors import AppError
from app.rules.weeks import week_window

_ID_ALPHABET = string.ascii_lowercase + string.digits


def new_id(prefix: str) -> str:
    """A new row id like `i_7k3m9q2x` (matches the id CHECK, never collides with seed ids)."""
    return f"{prefix}_{''.join(secrets.choice(_ID_ALPHABET) for _ in range(8))}"


async def bump_team(session: AsyncSession, team_id: str) -> int:
    """FIRST statement of every team-scoped write (plan 3.14, docs/DB_SCHEMA.md).

    It takes the team row lock before any other lock, so concurrent writes in one team
    queue in a fixed order and can't deadlock, and it bumps the cache version so a cached
    read model built before this write can never be served after it. Returns the new
    version, which is also the id of the live event this write sends (API contracts 10)."""
    version = await session.scalar(
        update(m.Team)
        .where(m.Team.id == team_id)
        .values(cache_version=m.Team.cache_version + 1)
        .returning(m.Team.cache_version)
    )
    if version is None:
        raise AppError(404, "not_found", "No such team.")
    return int(version)


async def team_state(session: AsyncSession, team_id: str) -> tuple[int, ZoneInfo]:
    """The team's cache version and company time zone, in one primary-key lookup: what a
    cached read needs before it can build its key (plan 3.14). Read before anything else
    in the request's read, so a cached result is never older than its version."""
    row = (
        await session.execute(
            select(m.Team.cache_version, m.Company.timezone)
            .join(m.Company, m.Company.id == m.Team.company_id)
            .where(m.Team.id == team_id)
        )
    ).one_or_none()
    if row is None:
        raise AppError(404, "not_found", "No such team.")
    return int(row.cache_version), ZoneInfo(row.timezone)


async def team_tz(session: AsyncSession, team_id: str) -> ZoneInfo:
    name = await session.scalar(
        select(m.Company.timezone)
        .join(m.Team, m.Team.company_id == m.Company.id)
        .where(m.Team.id == team_id)
    )
    if name is None:
        raise AppError(404, "not_found", "No such team.")
    return ZoneInfo(name)


async def user_refs(session: AsyncSession, ids: Iterable[str]) -> dict[str, dict[str, str]]:
    wanted = set(ids)
    if not wanted:
        return {}
    rows = await session.execute(select(m.User.id, m.User.name).where(m.User.id.in_(wanted)))
    return {r.id: {"id": r.id, "name": r.name} for r in rows}


def week_label(week: date) -> str:
    """`Nov 2`, as in the seed's Issue titles (`New deals closed, week of Nov 2`)."""
    return f"{week:%b} {week.day}"


def require_shown_week(week: date, now: datetime, tz: ZoneInfo) -> None:
    """Scores and Make it an Issue only work on a Monday inside the 13 shown weeks."""
    if week not in week_window(now, tz):
        raise AppError(
            422,
            "week_out_of_range",
            "The week must be a Monday within the 13 weeks shown on the Scorecard.",
        )


async def is_eligible_owner(session: AsyncSession, user_id: str, team_id: str) -> bool:
    """Decision 5: not an Observer, and an Admin or a member of the team (the role trigger
    enforces the same rule in the database)."""
    role = await session.scalar(select(m.User.role).where(m.User.id == user_id))
    if role is None or role == "observer":
        return False
    if role == "admin":
        return True
    member = await session.scalar(
        select(m.Membership.user_id).where(
            m.Membership.user_id == user_id, m.Membership.team_id == team_id
        )
    )
    return member is not None
