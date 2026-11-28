"""Seed loader: `python -m app.seed [--reset]` (plan 3.11, brief 2.7).

Loads seed/seed.json in one transaction as eos_owner:
- Seeds once: if the seed company already exists, it does nothing at all. `migrate` runs
  the seed on every `docker compose up`, so re-inserting "missing" rows would bring back
  rows deleted in the app (a cleared score, say). One transaction means a database either
  has the whole seed or none of it, so the company row is a reliable marker.
- Inserts use ON CONFLICT DO NOTHING by seed id as a second guard.
- --reset truncates every app table first (tests and the rules report's scratch database).
- Writes the frozen summaries of the ended seeded meetings (plan 3.9). A meeting without
  `ended_at` is loaded as active, in its first section, with no summary.
- Then replaces the database's cache generation in Redis, which orphans every cached
  reference entry (plan 3.14). `run()` alone (tests, the rules report) never touches Redis.
"""

import argparse
import asyncio
import json
import logging
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Table, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app import models as m
from app.cache import rotate_generation
from app.config import get_settings
from app.logging import setup_logging
from app.rules.meetings import scorecard_week_for
from app.services.summaries import meeting_snapshot

log = logging.getLogger("eos.seed")

# FK order. TRUNCATE ... CASCADE handles the reverse order for --reset.
TRUNCATE_ALL = text(
    "TRUNCATE companies, users, teams, memberships, measurables, scores, rocks, milestones,"
    " issues, todos, meetings, meeting_attendees, meeting_ratings, meeting_summaries,"
    " clock_anchor RESTART IDENTITY CASCADE"
)


def _ts(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"seed timestamp without a time zone: {value!r}")
    return parsed.astimezone(UTC)


def _day(value: str) -> date:
    return date.fromisoformat(value)


def _num(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def read_seed(path: Path) -> dict[str, Any]:
    # Floats as Decimal: scores like 4.1 and goals like 3.0 must stay exact.
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def meeting_row(mt: Mapping[str, Any], tz: ZoneInfo) -> dict[str, Any]:
    started_at = _ts(mt["started_at"])
    ended_at = _ts(mt.get("ended_at"))
    if started_at is None:
        raise ValueError(f"seed meeting {mt['id']!r} has no started_at")
    return {
        "id": mt["id"],
        "team_id": mt["team_id"],
        "facilitator_id": mt["facilitator_id"],
        "started_at": started_at,
        "ended_at": ended_at,
        # Ended seeded meetings have no section history (docs/DB_SCHEMA.md); an active
        # one is in its first section, which started with the meeting.
        "section": "conclude" if ended_at else "scorecard",
        "section_started_at": None if ended_at else started_at,
        "scorecard_week": scorecard_week_for(started_at, tz),
    }


def seed_rows(raw: Mapping[str, Any]) -> list[tuple[Table, list[dict[str, Any]]]]:
    """Seed JSON -> table rows, in foreign-key order. Pure, so it can be tested alone."""
    company = raw["company"]
    tz = ZoneInfo(company["timezone"])

    def goal(g: Mapping[str, Any]) -> dict[str, Any]:
        if g["type"] == "between":
            return {"goal_type": "between", "goal_min": _num(g["min"]), "goal_max": _num(g["max"])}
        return {"goal_type": g["type"], "goal_value": _num(g["value"])}

    def issue_source(source: Mapping[str, Any] | None) -> dict[str, Any]:
        if source is None:
            return {"source_kind": None}
        return {
            "source_kind": "measurable_week",
            "source_measurable_id": source["measurable_id"],
            "source_week_start": _day(source["week_start"]),
        }

    meetings = raw["meetings"]
    return [
        (
            m.Company.__table__,
            [{"id": company["id"], "name": company["name"], "timezone": company["timezone"]}],
        ),
        (
            m.User.__table__,
            [{**u, "company_id": company["id"]} for u in raw["users"]],
        ),
        (
            m.Team.__table__,
            [{**t, "company_id": company["id"]} for t in raw["teams"]],
        ),
        (m.Membership.__table__, list(raw["memberships"])),
        (
            m.Measurable.__table__,
            [
                {
                    "id": x["id"],
                    "team_id": x["team_id"],
                    "owner_id": x["owner_id"],
                    "name": x["name"],
                    "unit": x["unit"],
                    "goal_value": None,
                    "goal_min": None,
                    "goal_max": None,
                    **goal(x["goal"]),
                }
                for x in raw["measurables"]
            ],
        ),
        (
            m.Score.__table__,
            [
                {
                    "measurable_id": s["measurable_id"],
                    "week_start": _day(s["week_start"]),
                    "value": _num(s["value"]),
                }
                for s in raw["scores"]
            ],
        ),
        (m.Rock.__table__, list(raw["rocks"])),
        (
            m.Milestone.__table__,
            [{**ms, "due_date": _day(ms["due_date"])} for ms in raw["milestones"]],
        ),
        (
            m.Issue.__table__,
            [
                {
                    "id": i["id"],
                    "team_id": i["team_id"],
                    "owner_id": i["owner_id"],
                    "title": i["title"],
                    "priority": i["priority"],
                    "created_at": _ts(i["created_at"]),
                    "solved_at": _ts(i["solved_at"]),
                    "resolution_note": i["resolution_note"],
                    "source_measurable_id": None,
                    "source_week_start": None,
                    **issue_source(i["source"]),
                }
                for i in raw["issues"]
            ],
        ),
        (
            m.Todo.__table__,
            [
                {
                    "id": t["id"],
                    "team_id": t["team_id"],
                    "owner_id": t["owner_id"],
                    "title": t["title"],
                    "due_date": _day(t["due_date"]),
                    "done_at": _ts(t["done_at"]),
                    "source_issue_id": t["source_issue_id"],
                    "created_at": _ts(t["created_at"]),
                }
                for t in raw["todos"]
            ],
        ),
        (
            m.Meeting.__table__,
            [meeting_row(mt, tz) for mt in meetings],
        ),
        (
            m.MeetingAttendee.__table__,
            [
                {"meeting_id": mt["id"], "user_id": uid, "joined_at": _ts(mt["started_at"])}
                for mt in meetings
                for uid in mt["attendee_ids"]
            ],
        ),
        (
            m.MeetingRating.__table__,
            [
                {
                    "meeting_id": mt["id"],
                    "user_id": r["user_id"],
                    "rating": r["rating"],
                    "updated_at": None,
                }
                for mt in meetings
                for r in mt["ratings"]
            ],
        ),
    ]


async def load(conn: AsyncConnection, raw: Mapping[str, Any]) -> dict[str, int]:
    """Insert the seed and the ended seeded meetings' snapshots, unless this database was
    already seeded. Returns rows inserted per table (all zero when already seeded)."""
    tables = seed_rows(raw)
    company_id = raw["company"]["id"]
    if await conn.scalar(select(m.Company.id).where(m.Company.id == company_id)) is not None:
        return {table.name: 0 for table, _ in tables} | {"meeting_summaries": 0}

    inserted: dict[str, int] = {}
    for table, rows in tables:
        if rows:
            result = await conn.execute(insert(table).values(rows).on_conflict_do_nothing())
            inserted[table.name] = result.rowcount or 0

    snapshots = 0
    for meeting in raw["meetings"]:
        if meeting.get("ended_at") is None:
            continue  # active meeting: its summary is written when it ends
        exists = await conn.scalar(
            select(m.MeetingSummary.meeting_id).where(m.MeetingSummary.meeting_id == meeting["id"])
        )
        if exists is None:
            document = await meeting_snapshot(conn, meeting["id"])
            await conn.execute(
                insert(m.MeetingSummary.__table__)
                .values(
                    meeting_id=meeting["id"], summary=document, created_at=_ts(meeting["ended_at"])
                )
                .on_conflict_do_nothing()
            )
            snapshots += 1
    inserted["meeting_summaries"] = snapshots
    return inserted


async def run(*, reset: bool, seed_path: Path, database_url: str) -> dict[str, int]:
    raw = read_seed(seed_path)
    engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"application_name": "eos-seed"}},
    )
    try:
        async with engine.begin() as conn:  # one transaction: all or nothing
            if reset:
                await conn.execute(TRUNCATE_ALL)
            return await load(conn, raw)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Load seed/seed.json into the database.")
    parser.add_argument("--reset", action="store_true", help="truncate all app tables first")
    args = parser.parse_args()
    settings = get_settings()
    setup_logging(settings.log_level)
    inserted = asyncio.run(
        run(
            reset=args.reset,
            seed_path=Path(settings.seed_path),
            database_url=settings.owner_database_url,
        )
    )
    total = sum(inserted.values())
    log.info(
        "seed loaded" if total else "seed already present, nothing inserted",
        extra={"reset": args.reset, "inserted": inserted},
    )
    # After the commit: every reference entry cached for this database is orphaned (plan
    # 3.14). With the cache on, no Redis means no start: the API must not come up on top
    # of reference data cached before this seed. With it off, try anyway, so turning it
    # back on later can't find entries from before.
    try:
        asyncio.run(rotate_generation(settings))
    except Exception:
        if settings.cache_enabled:
            log.exception("could not replace the cache generation in Redis")
            raise SystemExit(1) from None
        log.warning("cache off and Redis unreachable: generation not replaced")
    else:
        log.info("cache generation replaced")


if __name__ == "__main__":
    main()
