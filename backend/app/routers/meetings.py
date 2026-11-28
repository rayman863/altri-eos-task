"""Meetings and the live stream (API contracts sections 9 and 10)."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.authz import MeetingFacilitator, MeetingRater, MeetingRead, Now, TeamRead, TeamWrite
from app.cache import ReadCache, RequestCache
from app.db import DbSession
from app.errors import AppError
from app.realtime import Hub, stream
from app.schemas import (
    ActiveMeeting,
    AdvanceIn,
    Empty,
    MeetingState,
    MeetingSummary,
    PastMeetingList,
    RatingIn,
    RatingOut,
)
from app.services import meetings

router = APIRouter(tags=["Meetings"])

SSE_HEADERS = {
    # no-transform: proxies (Next.js compression included) must not gzip or buffer events
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}


@router.get("/teams/{team_id}/meetings/active", response_model=ActiveMeeting)
async def active_meeting(access: TeamRead, session: DbSession, now: Now, cache: ReadCache) -> dict:
    return {"meeting": await meetings.read_active_meeting(session, cache, access.team_id, now)}


@router.get("/teams/{team_id}/meetings", response_model=PastMeetingList)
async def past_meetings(access: TeamRead, session: DbSession, cache: ReadCache) -> dict:
    """Ended meetings, newest first, each linking to its frozen summary."""
    return await meetings.past_meetings(session, access.team_id, cache)


@router.post("/teams/{team_id}/meetings", response_model=MeetingState, status_code=201)
async def start_meeting(
    access: TeamWrite, session: DbSession, now: Now, body: Empty | None = None
) -> dict:
    return await meetings.start(session, access, now)


@router.get("/meetings/{meeting_id}", response_model=MeetingState)
async def get_meeting(access: MeetingRead, session: DbSession, now: Now, cache: ReadCache) -> dict:
    return await meetings.read_meeting_state(
        session, cache, access.team_id, access.resource_id, now
    )


@router.post("/meetings/{meeting_id}/join", response_model=MeetingState)
async def join_meeting(
    access: MeetingRead, session: DbSession, now: Now, body: Empty | None = None
) -> dict:
    return await meetings.join(session, access, now)


@router.post("/meetings/{meeting_id}/advance", response_model=MeetingState)
async def advance_meeting(
    access: MeetingFacilitator, body: AdvanceIn, session: DbSession, now: Now
) -> dict:
    return await meetings.advance(session, access, body.expected_section, now)


@router.post("/meetings/{meeting_id}/end", response_model=MeetingState)
async def end_meeting(
    access: MeetingFacilitator, session: DbSession, now: Now, body: Empty | None = None
) -> dict:
    return await meetings.end(session, access, now)


@router.put("/meetings/{meeting_id}/rating", response_model=RatingOut)
async def rate_meeting(access: MeetingRater, body: RatingIn, session: DbSession, now: Now) -> dict:
    return await meetings.rate(session, access, body.rating, now)


@router.get("/meetings/{meeting_id}/summary", response_model=MeetingSummary)
async def meeting_summary(access: MeetingRead, session: DbSession, cache: ReadCache) -> dict:
    return await meetings.summary(session, access.resource_id, cache)


@router.get(
    "/teams/{team_id}/events",
    tags=["Live updates"],
    summary="Server-Sent Events: snapshot, team.changed, meeting.state, meeting.ended",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "An SSE stream"}},
)
async def events(access: TeamRead, request: Request) -> StreamingResponse:
    """Authorized once at connect, like any team read. The request's own DB session ends
    when this function returns (before streaming), and each snapshot uses a short-lived
    session, so open streams never hold pool connections (plan 3.12)."""
    hub: Hub = request.app.state.hub
    if not hub.has_room(access.user.id):
        raise AppError(
            429,
            "rate_limited",
            "Too many open live streams for this user.",
            headers={"Retry-After": "5"},
        )
    sessionmaker = request.app.state.sessionmaker
    clock = request.app.state.clock
    read_cache = request.app.state.cache
    team_id = access.team_id

    async def snapshot():  # noqa: ANN202 - an Event
        cache = RequestCache(read_cache, {})  # the meeting state entry every reader shares
        async with sessionmaker() as session:
            return await meetings.snapshot_event(session, team_id, clock.now(), cache)

    return StreamingResponse(
        stream(hub, team_id, access.user.id, snapshot),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
