"""Rocks: the current quarter's Rocks with computed status and progress (seed data, read-only),
and Make it an Issue from an off-track Rock (bonus 3)."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.authz import TeamAccess
from app.cache import RequestCache
from app.errors import AppError
from app.rules.rocks import milestone_past_due, rock_progress, rock_status
from app.rules.types import Milestone
from app.rules.weeks import quarter_of, today
from app.services.common import bump_team, team_state, team_tz, user_refs
from app.services.issues import get_issue, insert_source_issue, open_issue_ids


async def list_rocks(
    session: AsyncSession, team_id: str, now: datetime, cache: RequestCache | None = None
) -> dict[str, Any]:
    """Cached per team version and company date (plan 3.14): status and past-due flags
    change with the date, and each Rock's open Issue (bonus 3) with the team's writes."""
    if cache is None:
        return await _list_rocks(session, team_id, now)
    version, tz = await team_state(session, team_id)
    return await cache.get_or_set(
        f"team:{team_id}:v{version}:rocks:{today(now, tz)}",
        cache.cache.ttl_team,
        lambda: _list_rocks(session, team_id, now),
    )


async def _list_rocks(session: AsyncSession, team_id: str, now: datetime) -> dict[str, Any]:
    tz = await team_tz(session, team_id)
    day = today(now, tz)
    quarter = quarter_of(day)
    rocks = list(
        await session.execute(
            select(m.Rock.id, m.Rock.title, m.Rock.owner_id, m.Rock.status)
            .where(m.Rock.team_id == team_id, m.Rock.quarter == quarter)
            .order_by(m.Rock.id)
        )
    )
    milestones: dict[str, list[Any]] = {}
    for r in await session.execute(
        select(
            m.Milestone.id,
            m.Milestone.rock_id,
            m.Milestone.title,
            m.Milestone.due_date,
            m.Milestone.done,
        )
        .where(m.Milestone.rock_id.in_([r.id for r in rocks]))
        .order_by(m.Milestone.due_date, m.Milestone.id)
    ):
        milestones.setdefault(r.rock_id, []).append(r)
    owners = await user_refs(session, (r.owner_id for r in rocks))
    open_issues = await open_issue_ids(session, team_id, "rock")

    items = []
    for rock in rocks:
        rows = milestones.get(rock.id, [])
        rules = [Milestone(ms.id, ms.due_date, ms.done) for ms in rows]
        items.append(
            {
                "id": rock.id,
                "title": rock.title,
                "owner": owners[rock.owner_id],
                "seeded_status": rock.status,
                "status": rock_status(rock.status, rules, day),
                "progress_percent": rock_progress(rock.status, rules),
                "milestones": [
                    {
                        "id": ms.id,
                        "title": ms.title,
                        "due_date": ms.due_date,
                        "done": ms.done,
                        "past_due": milestone_past_due(rule, day),
                    }
                    for ms, rule in zip(rows, rules, strict=True)
                ],
                "open_issue_id": open_issues.get(rock.id),
            }
        )
    return {"quarter": quarter, "items": items}


async def make_issue_from_rock(
    session: AsyncSession, access: TeamAccess, rock_id: str, now: datetime
) -> tuple[dict[str, Any], bool]:
    """Bonus 3: Make it an Issue from an off-track Rock of this quarter (services/issues.py
    has the shared dedupe). Returns (issue, created); an open Issue for the Rock wins."""
    version = await bump_team(session, access.team_id)  # the team lock comes first
    rocks = (await _list_rocks(session, access.team_id, now))["items"]
    rock = next((r for r in rocks if r["id"] == rock_id), None)
    if rock is None:
        raise AppError(404, "not_found", "No such Rock this quarter.")
    if rock["open_issue_id"] is not None:
        return await get_issue(session, rock["open_issue_id"]), False
    if rock["status"] != "off_track":
        raise AppError(
            422,
            "rock_not_off_track",
            "Only an off-track Rock can become an Issue.",
            {"status": rock["status"]},
        )
    title = f"Rock off track: {rock['title']}"
    return await insert_source_issue(session, access, version, "rock", rock_id, title, now)
