"""The shared origin of the ticking business clock (plan 3.2, 3.13).

Every write is stamped with business time and every read applies the rules "as of now"
(decision 33), so all API processes must agree on "now", also across restarts. The one
`clock_anchor` row holds (app_now, real_now): business time `app_now` happened at real time
`real_now`, so every process computes now = app_now + (wall clock - real_now).

- The first process to start inserts the row; later ones (other workers, restarts) reuse
  it, so business time keeps counting forward and never jumps back to APP_NOW.
- If APP_NOW in the environment changes, the row is replaced on the next start, so a new
  APP_NOW takes effect. `docker compose down -v` (or `make reset`) also starts over.
"""

import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app import models as m
from app.clock import TickingClock, wall_clock

log = logging.getLogger("eos.clock")


async def ensure_clock_anchor(
    engine: AsyncEngine, app_now: datetime, wall: Callable[[], datetime] = wall_clock
) -> datetime:
    """The shared real-time anchor for `app_now` (inserted if missing or stale)."""
    async with engine.begin() as conn:
        statement = insert(m.ClockAnchor).values(id=1, app_now=app_now, real_now=wall())
        await conn.execute(
            statement.on_conflict_do_update(
                index_elements=[m.ClockAnchor.id],
                set_={
                    "app_now": statement.excluded.app_now,
                    "real_now": statement.excluded.real_now,
                },
                # Only a changed APP_NOW replaces the anchor; a restart keeps the old one.
                where=m.ClockAnchor.app_now != statement.excluded.app_now,
            )
        )
        real_now = await conn.scalar(select(m.ClockAnchor.real_now).where(m.ClockAnchor.id == 1))
    assert real_now is not None  # the upsert above guarantees the row
    return real_now


async def anchored_clock(
    engine: AsyncEngine, app_now: datetime, wall: Callable[[], datetime] = wall_clock
) -> TickingClock:
    real_now = await ensure_clock_anchor(engine, app_now, wall)
    clock = TickingClock(app_now, real_anchor=real_now, wall=wall)
    log.info(
        "business clock anchored",
        extra={
            "app_now": app_now.isoformat(),
            "anchored_at": real_now.isoformat(),
            "now": clock.now().isoformat(),
        },
    )
    return clock
