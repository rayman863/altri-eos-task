"""Level 10 Meetings (plan 3.7, API contracts section 9).

The database is the source of truth: section, section_started_at, facilitator and ended_at
live in `meetings`, so a late join, a refresh or a reconnect (facilitator included) just
reads the state again. Every command is a team write: it takes the team lock first
(`bump_team`), changes the meeting, and emits a live event in the same transaction, which
Postgres delivers only on commit.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.authz import ResourceAccess, TeamAccess
from app.cache import SUMMARY_TTL_S, RequestCache
from app.errors import AppError
from app.realtime import Event, emit
from app.rules.meetings import meeting_rating, scorecard_week_for
from app.services.common import bump_team, new_id, team_state, team_tz
from app.services.summaries import meeting_snapshot

SECTIONS = ("scorecard", "ids", "conclude")
SECTION_DURATION_S = {"scorecard": 300, "ids": 3600, "conclude": 600}


async def active_meeting_id(session: AsyncSession, team_id: str) -> str | None:
    return await session.scalar(
        select(m.Meeting.id).where(m.Meeting.team_id == team_id, m.Meeting.ended_at.is_(None))
    )


async def meeting_state(session: AsyncSession, meeting_id: str, now: datetime) -> dict[str, Any]:
    """The meeting state object (API contracts section 9): returned by every meeting
    endpoint and pushed as the `meeting.state` event. `server_now` lets clients run the
    section timer from the server's clock; nothing advances on its own."""
    return with_now(await _meeting_core(session, meeting_id), now)


def with_now(state: dict[str, Any], now: datetime) -> dict[str, Any]:
    """A state with this response's `server_now`: the one part never cached (plan 3.14)."""
    return {**state, "server_now": now}


async def read_meeting_state(
    session: AsyncSession, cache: RequestCache, team_id: str, meeting_id: str, now: datetime
) -> dict[str, Any]:
    """`meeting_state` for reads, cached per team version: every meeting command bumps it."""
    version, _ = await team_state(session, team_id)
    state = await cache.get_or_set(
        f"team:{team_id}:v{version}:meeting:{meeting_id}",
        cache.cache.ttl_team,
        lambda: _meeting_core(session, meeting_id),
    )
    return with_now(state, now)


async def read_active_meeting(
    session: AsyncSession, cache: RequestCache, team_id: str, now: datetime
) -> dict[str, Any] | None:
    """The team's active meeting state (or None) for reads, cached per team version."""
    version, _ = await team_state(session, team_id)

    async def compute() -> dict[str, Any] | None:
        active = await active_meeting_id(session, team_id)
        return await _meeting_core(session, active) if active else None

    state = await cache.get_or_set(
        f"team:{team_id}:v{version}:meeting:active", cache.cache.ttl_team, compute
    )
    return with_now(state, now) if state is not None else None


async def _meeting_core(session: AsyncSession, meeting_id: str) -> dict[str, Any]:
    """Everything in the state except `server_now` (it keeps its place, set to None)."""
    mt = (
        await session.execute(
            select(
                m.Meeting.id,
                m.Meeting.team_id,
                m.Meeting.section,
                m.Meeting.section_started_at,
                m.Meeting.started_at,
                m.Meeting.ended_at,
                m.Meeting.scorecard_week,
                m.Meeting.facilitator_id,
                m.User.name.label("facilitator_name"),
            )
            .join(m.User, m.User.id == m.Meeting.facilitator_id)
            .where(m.Meeting.id == meeting_id)
        )
    ).one_or_none()
    if mt is None:
        raise AppError(404, "not_found", "No such meeting.")
    attendees = list(
        await session.execute(
            select(m.User.id, m.User.name, m.User.role, m.MeetingAttendee.joined_at)
            .join(m.MeetingAttendee, m.MeetingAttendee.user_id == m.User.id)
            .where(m.MeetingAttendee.meeting_id == meeting_id)
            .order_by(m.MeetingAttendee.joined_at, m.User.id)
        )
    )
    ratings = list(
        await session.execute(
            select(m.MeetingRating.user_id, m.MeetingRating.rating)
            .where(m.MeetingRating.meeting_id == meeting_id)
            .order_by(m.MeetingRating.user_id)
        )
    )
    average = meeting_rating(r.rating for r in ratings)
    return {
        "id": mt.id,
        "team_id": mt.team_id,
        "status": "active" if mt.ended_at is None else "ended",
        "section": mt.section,
        "section_started_at": mt.section_started_at,
        "section_duration_s": SECTION_DURATION_S[mt.section],
        "server_now": None,
        "started_at": mt.started_at,
        "ended_at": mt.ended_at,
        "scorecard_week": mt.scorecard_week,
        "facilitator": {"id": mt.facilitator_id, "name": mt.facilitator_name},
        "attendees": [
            {"id": a.id, "name": a.name, "role": a.role, "joined_at": a.joined_at}
            for a in attendees
        ],
        "ratings": [{"user_id": r.user_id, "rating": r.rating} for r in ratings],
        "average_rating": float(average) if average is not None else None,
    }


async def snapshot_event(
    session: AsyncSession, team_id: str, now: datetime, cache: RequestCache | None = None
) -> Event:
    """What a live stream sends first, and again after a resync: the team's cache version
    (also the event id) and its active meeting, if any. With a cache, the meeting state is
    shared with every other reader (a restart reconnects every open tab at once)."""
    version = await session.scalar(select(m.Team.cache_version).where(m.Team.id == team_id))
    if cache is not None:
        state = await read_active_meeting(session, cache, team_id, now)
    else:
        active = await active_meeting_id(session, team_id)
        state = await meeting_state(session, active, now) if active else None
    return Event(
        "snapshot",
        int(version or 0),
        {"team_id": team_id, "cache_version": int(version or 0), "active_meeting": state},
    )


async def _locked(session: AsyncSession, meeting_id: str) -> Any:
    row = (
        await session.execute(
            select(
                m.Meeting.id,
                m.Meeting.team_id,
                m.Meeting.facilitator_id,
                m.Meeting.section,
                m.Meeting.ended_at,
            )
            .where(m.Meeting.id == meeting_id)
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise AppError(404, "not_found", "No such meeting.")
    return row


def _require_facilitator(access: ResourceAccess, meeting: Any) -> None:
    if access.user.id != meeting.facilitator_id:
        raise AppError(403, "not_facilitator", "Only the facilitator can do that.")


def _require_active(meeting: Any) -> None:
    if meeting.ended_at is not None:
        raise AppError(409, "meeting_ended", "This meeting has ended.")


async def _state_event(
    session: AsyncSession, team_id: str, version: int, meeting_id: str, now: datetime
) -> dict[str, Any]:
    state = await meeting_state(session, meeting_id, now)
    await emit(session, team_id, version, "meeting.state", state)
    return state


async def start(session: AsyncSession, access: TeamAccess, now: datetime) -> dict[str, Any]:
    """The caller (an Admin or Team Member: TeamWrite) facilitates and attends first."""
    version = await bump_team(session, access.team_id)
    active = await active_meeting_id(session, access.team_id)
    if active is not None:
        raise AppError(
            409,
            "meeting_already_active",
            "This team already has an active meeting.",
            {"meeting_id": active},
        )
    tz = await team_tz(session, access.team_id)
    meeting_id = new_id("mt")
    await session.execute(
        insert(m.Meeting).values(
            id=meeting_id,
            team_id=access.team_id,
            facilitator_id=access.user.id,
            started_at=now,
            section="scorecard",
            section_started_at=now,
            scorecard_week=scorecard_week_for(now, tz),  # the last closed week
        )
    )
    await session.execute(
        insert(m.MeetingAttendee).values(
            meeting_id=meeting_id, user_id=access.user.id, joined_at=now
        )
    )
    return await _state_event(session, access.team_id, version, meeting_id, now)


async def join(session: AsyncSession, access: ResourceAccess, now: datetime) -> dict[str, Any]:
    """Anyone who can read the team, Observers included. Idempotent: joining again keeps
    the first joined_at and sends no event."""
    version = await bump_team(session, access.team_id)
    meeting = await _locked(session, access.resource_id)
    _require_active(meeting)
    joined = await session.scalar(
        insert(m.MeetingAttendee)
        .values(meeting_id=meeting.id, user_id=access.user.id, joined_at=now)
        .on_conflict_do_nothing()
        .returning(m.MeetingAttendee.user_id)
    )
    if joined is None:
        return await meeting_state(session, meeting.id, now)
    return await _state_event(session, access.team_id, version, meeting.id, now)


async def advance(
    session: AsyncSession, access: ResourceAccess, expected: str, now: datetime
) -> dict[str, Any]:
    """Facilitator only, forward only, compare-and-set on the expected section, so a double
    click can't skip a section."""
    version = await bump_team(session, access.team_id)
    meeting = await _locked(session, access.resource_id)
    _require_facilitator(access, meeting)
    _require_active(meeting)
    if meeting.section != expected:
        raise AppError(
            409,
            "section_changed",
            "The meeting already moved on.",
            {"section": meeting.section},
        )
    if meeting.section == SECTIONS[-1]:
        raise AppError(409, "last_section", "Conclude is the last section: end the meeting.")
    following = SECTIONS[SECTIONS.index(meeting.section) + 1]
    await session.execute(
        update(m.Meeting)
        .where(
            m.Meeting.id == meeting.id,
            m.Meeting.section == expected,
            m.Meeting.ended_at.is_(None),
        )
        .values(section=following, section_started_at=now)
    )
    return await _state_event(session, access.team_id, version, meeting.id, now)


async def end(session: AsyncSession, access: ResourceAccess, now: datetime) -> dict[str, Any]:
    """Facilitator only, from any section. Freezes the summary in the same transaction
    (plan 3.9), so later edits can't change it."""
    version = await bump_team(session, access.team_id)
    meeting = await _locked(session, access.resource_id)
    _require_facilitator(access, meeting)
    _require_active(meeting)
    await session.execute(update(m.Meeting).where(m.Meeting.id == meeting.id).values(ended_at=now))
    snapshot = await meeting_snapshot(await session.connection(), meeting.id)
    await session.execute(
        insert(m.MeetingSummary).values(meeting_id=meeting.id, summary=snapshot, created_at=now)
    )
    await emit(session, access.team_id, version, "meeting.ended", {"meeting_id": meeting.id})
    return await meeting_state(session, meeting.id, now)


async def rate(
    session: AsyncSession, access: ResourceAccess, rating: int, now: datetime
) -> dict[str, Any]:
    """An attending Admin or Team Member, 1 to 10, changeable until the meeting ends."""
    version = await bump_team(session, access.team_id)
    meeting = await _locked(session, access.resource_id)
    if access.user.role == "observer":
        raise AppError(403, "forbidden", "Observers can join meetings but not rate them.")
    attending = await session.scalar(
        select(m.MeetingAttendee.user_id).where(
            m.MeetingAttendee.meeting_id == meeting.id,
            m.MeetingAttendee.user_id == access.user.id,
        )
    )
    if attending is None:
        raise AppError(403, "not_attendee", "Join the meeting before rating it.")
    _require_active(meeting)
    statement = insert(m.MeetingRating).values(
        meeting_id=meeting.id, user_id=access.user.id, rating=rating, updated_at=now
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[m.MeetingRating.meeting_id, m.MeetingRating.user_id],
            set_={
                "rating": statement.excluded.rating,
                "updated_at": statement.excluded.updated_at,
            },
        )
    )
    await _state_event(session, access.team_id, version, meeting.id, now)
    return {"user_id": access.user.id, "rating": rating}


async def past_meetings(
    session: AsyncSession, team_id: str, cache: RequestCache | None = None
) -> dict[str, Any]:
    """The team's ended meetings, newest first, each described from its frozen summary, so
    the list always agrees with the summary page (plan 3.9). Cached per team version:
    ending a meeting bumps it."""
    if cache is None:
        return await _past_meetings(session, team_id)
    version, _ = await team_state(session, team_id)
    return await cache.get_or_set(
        f"team:{team_id}:v{version}:meetings:past",
        cache.cache.ttl_team,
        lambda: _past_meetings(session, team_id),
    )


async def _past_meetings(session: AsyncSession, team_id: str) -> dict[str, Any]:
    rows = await session.scalars(
        select(m.MeetingSummary.summary)
        .join(m.Meeting, m.Meeting.id == m.MeetingSummary.meeting_id)
        .where(m.Meeting.team_id == team_id, m.Meeting.ended_at.is_not(None))
        .order_by(m.Meeting.ended_at.desc(), m.Meeting.id)
    )
    items = []
    for snap in rows:
        facilitator = snap["facilitator_id"]
        items.append(
            {
                "id": snap["meeting_id"],
                "started_at": snap["started_at"],
                "ended_at": snap["ended_at"],
                "facilitator": {"id": facilitator, "name": snap["labels"]["users"][facilitator]},
                "rating": snap["rating"],
                "attendee_count": len(snap["attendee_ids"]),
                "issues_solved": len(snap["issues_solved"]),
                "todos_created": len(snap["todos_created"]),
            }
        )
    return {"items": items}


async def summary(
    session: AsyncSession, meeting_id: str, cache: RequestCache | None = None
) -> dict[str, Any]:
    """The frozen snapshot, never recomputed (plan 3.9). Immutable once written, so with a
    cache it is kept for 24 h (only a new seed generation replaces it)."""
    if cache is not None:
        return await cache.get_or_set(
            f"summary:{meeting_id}", SUMMARY_TTL_S, lambda: summary(session, meeting_id)
        )
    ended_at = await session.scalar(select(m.Meeting.ended_at).where(m.Meeting.id == meeting_id))
    if ended_at is None:
        raise AppError(409, "meeting_not_ended", "The meeting hasn't ended yet.")
    document = await session.scalar(
        select(m.MeetingSummary.summary).where(m.MeetingSummary.meeting_id == meeting_id)
    )
    if document is None:  # ended without a snapshot: never recompute one here
        raise AppError(404, "not_found", "No summary for this meeting.")
    return document
