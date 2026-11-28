"""Session and team read models: the user switcher, /me, team list and team detail."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.authz import CurrentUser
from app.cache import RequestCache
from app.rules.weeks import current_week, last_closed_week, today
from app.services.meetings import meeting_state, read_active_meeting


async def seed_users(
    session: AsyncSession, cache: RequestCache | None = None
) -> list[dict[str, Any]]:
    """The login switcher's list. Users and memberships are seed data with no edit
    endpoint, so it is cached as reference data (plan 3.14)."""
    if cache is not None:
        return await cache.get_or_set("ref:users", cache.cache.ttl_ref, lambda: seed_users(session))
    teams: dict[str, list[dict[str, str]]] = {}
    for r in await session.execute(
        select(m.Membership.user_id, m.Team.id, m.Team.name)
        .join(m.Team, m.Team.id == m.Membership.team_id)
        .order_by(m.Membership.user_id, m.Team.id)
    ):
        teams.setdefault(r.user_id, []).append({"id": r.id, "name": r.name})
    users = await session.execute(
        select(m.User.id, m.User.name, m.User.email, m.User.role).order_by(m.User.id)
    )
    return [
        {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "teams": teams.get(u.id, [])}
        for u in users
    ]


async def visible_teams(session: AsyncSession, user: CurrentUser) -> list[Any]:
    query = select(m.Team.id, m.Team.name).order_by(m.Team.id)
    if not user.is_admin:
        query = query.where(m.Team.id.in_(user.team_ids))
    return list(await session.execute(query))


async def me(session: AsyncSession, user: CurrentUser, now: datetime) -> dict[str, Any]:
    teams = await visible_teams(session, user)
    company = (
        await session.execute(
            select(m.Company.id, m.Company.name, m.Company.timezone)
            .join(m.User, m.User.company_id == m.Company.id)
            .where(m.User.id == user.id)
        )
    ).one()
    zone = ZoneInfo(company.timezone)  # every week and "today" is in company time
    return {
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role},
        "teams": [{"id": t.id, "name": t.name, "can_write": user.can_write(t.id)} for t in teams],
        "company": {"id": company.id, "name": company.name, "timezone": company.timezone},
        "clock": {
            "now": now,
            "today": today(now, zone),
            "current_week": current_week(now, zone),
            "last_closed_week": last_closed_week(now, zone),
        },
    }


async def active_meeting_ids(session: AsyncSession, team_ids: list[str]) -> dict[str, str]:
    rows = await session.execute(
        select(m.Meeting.team_id, m.Meeting.id).where(
            m.Meeting.team_id.in_(team_ids), m.Meeting.ended_at.is_(None)
        )
    )
    return {r.team_id: r.id for r in rows}


async def team_list(session: AsyncSession, user: CurrentUser) -> list[dict[str, Any]]:
    teams = await visible_teams(session, user)
    active = await active_meeting_ids(session, [t.id for t in teams])
    return [{"id": t.id, "name": t.name, "active_meeting_id": active.get(t.id)} for t in teams]


async def team_detail(
    session: AsyncSession, team_id: str, now: datetime, cache: RequestCache | None = None
) -> dict[str, Any]:
    """Team, members and eligible owners (reference data) plus the active meeting (cached
    per team version), each from its own cache entry (plan 3.14)."""
    if cache is None:
        return await _team_detail(session, team_id, now)
    ref = await cache.get_or_set(
        f"team:{team_id}:ref", cache.cache.ttl_ref, lambda: _team_ref(session, team_id)
    )
    return {**ref, "active_meeting": await read_active_meeting(session, cache, team_id, now)}


async def _team_detail(session: AsyncSession, team_id: str, now: datetime) -> dict[str, Any]:
    active = await active_meeting_ids(session, [team_id])
    return {
        **await _team_ref(session, team_id),
        "active_meeting": (
            await meeting_state(session, active[team_id], now) if team_id in active else None
        ),
    }


async def _team_ref(session: AsyncSession, team_id: str) -> dict[str, Any]:
    team = (await session.execute(select(m.Team.id, m.Team.name).where(m.Team.id == team_id))).one()
    members = list(
        await session.execute(
            select(m.User.id, m.User.name, m.User.role)
            .join(m.Membership, m.Membership.user_id == m.User.id)
            .where(m.Membership.team_id == team_id)
            .order_by(m.User.id)
        )
    )
    admins = list(
        await session.execute(
            select(m.User.id, m.User.name).where(m.User.role == "admin").order_by(m.User.id)
        )
    )
    # Decision 5: non-Observer members plus every Admin.
    eligible = {u.id: u.name for u in members if u.role != "observer"} | {
        a.id: a.name for a in admins
    }
    return {
        "id": team.id,
        "name": team.name,
        "members": [{"id": u.id, "name": u.name, "role": u.role} for u in members],
        "eligible_owners": [{"id": i, "name": eligible[i]} for i in sorted(eligible)],
    }
