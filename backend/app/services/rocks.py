"""Rocks (read-only): the current quarter's Rocks with computed status and progress."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.cache import RequestCache
from app.rules.rocks import milestone_past_due, rock_progress, rock_status
from app.rules.types import Milestone
from app.rules.weeks import quarter_of, today
from app.services.common import team_state, team_tz, user_refs


async def list_rocks(
    session: AsyncSession, team_id: str, now: datetime, cache: RequestCache | None = None
) -> dict[str, Any]:
    """Rocks and milestones are seed data with no edit endpoint, so they are cached as
    reference data (replaced by every seed) per company date: status and past-due flags
    only change with the date (plan 3.14)."""
    if cache is None:
        return await _list_rocks(session, team_id, now)
    _, tz = await team_state(session, team_id)
    return await cache.get_or_set(
        f"team:{team_id}:rocks:{today(now, tz)}",
        cache.cache.ttl_ref,
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
            }
        )
    return {"quarter": quarter, "items": items}
