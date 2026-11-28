"""The one access policy (plan 3.6, API contracts "Access levels").

Every route declares what it needs with one of these dependencies:

- `SignedIn`: any valid session.
- `TeamRead` / `TeamWrite`: the `{team_id}` path parameter, checked for the caller.
- `IssueWrite`, `TodoWrite`: a resource fetched by id is resolved to its team first and then
  goes through the same team check, so a guessed id can't cross a team boundary.

Rules: Admin passes every team. A Team Member reads and writes their own teams. An Observer
only reads their own teams. An inaccessible team is 403, even for an unknown id; an Admin
(who could access it) gets 404 for an unknown team.

The route-table test (tests/api/test_authz_routes.py) walks every route, so an endpoint
added without one of these guards fails the suite.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Path, Request
from sqlalchemy import select

from app import models as m
from app.cache import ACCESS_TTL_S, RequestCache, for_request
from app.db import DbSession
from app.errors import AppError
from app.security import COOKIE_NAME, verify_session

ID_PATTERN = r"^[a-z0-9_]{1,64}$"

TeamIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Team id, e.g. team_lead")]
IssueIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Issue id, e.g. i5")]
TodoIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="To-Do id, e.g. t12")]
MeasurableIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Measurable id, e.g. m1")]

FORBIDDEN_TEAM = "You do not have access to this team."
READ_ONLY = "Observers can read this team but not change it."


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: str
    name: str
    email: str
    role: str
    team_ids: frozenset[str]
    session_epoch: int = 0

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def can_read(self, team_id: str) -> bool:
        return self.is_admin or team_id in self.team_ids

    def can_write(self, team_id: str) -> bool:
        return self.role != "observer" and self.can_read(team_id)


@dataclass(frozen=True, slots=True)
class TeamAccess:
    user: CurrentUser
    team_id: str
    can_write: bool


@dataclass(frozen=True, slots=True)
class ResourceAccess(TeamAccess):
    resource_id: str


async def load_user(
    session: DbSession, user_id: str, cache: RequestCache | None = None
) -> CurrentUser | None:
    """The user and their access facts. With a cache, the facts (role, team ids) come from
    it: they are seed data with no edit endpoint (plan 3.14). The session epoch never
    does: it changes on logout, and a logged-out token must stop working at once, so it
    is read from Postgres on every request."""
    if cache is None:
        return await _load_user(session, user_id)
    epoch = await session.scalar(select(m.User.session_epoch).where(m.User.id == user_id))
    if epoch is None:
        return None

    async def facts() -> dict | None:
        user = await _load_user(session, user_id)
        if user is None:  # removed since the epoch lookup (a seed reset): signed out
            return None
        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "team_ids": sorted(user.team_ids),
        }

    # note=False: every request reads these, so they stay out of its log line's outcome.
    f = await cache.get_or_set(f"user:{user_id}:access", ACCESS_TTL_S, facts, note=False)
    if f is None:
        return None
    return CurrentUser(f["id"], f["name"], f["email"], f["role"], frozenset(f["team_ids"]), epoch)


async def _load_user(session: DbSession, user_id: str) -> CurrentUser | None:
    row = (
        await session.execute(
            select(m.User.id, m.User.name, m.User.email, m.User.role, m.User.session_epoch).where(
                m.User.id == user_id
            )
        )
    ).one_or_none()
    if row is None:
        return None
    teams = await session.scalars(
        select(m.Membership.team_id).where(m.Membership.user_id == user_id)
    )
    return CurrentUser(row.id, row.name, row.email, row.role, frozenset(teams), row.session_epoch)


async def get_current_user(request: Request, session: DbSession) -> CurrentUser:
    settings = request.app.state.settings
    token = request.cookies.get(COOKIE_NAME)
    claims = (
        verify_session(settings.session_secret, token, settings.session_max_age_s)
        if token
        else None
    )
    user = await load_user(session, claims[0], for_request(request)) if claims else None
    # A token from before the user's last logout carries an older epoch.
    if user is None or claims is None or claims[1] != user.session_epoch:
        raise AppError(401, "unauthenticated", "Sign in first.")
    request.state.user_id = user.id  # for the request log
    return user


SignedIn = Annotated[CurrentUser, Depends(get_current_user)]


def get_now(request: Request) -> datetime:
    """The business clock (APP_NOW-based), read once per request."""
    return request.app.state.clock.now()


Now = Annotated[datetime, Depends(get_now)]


async def check_team(
    session: DbSession, user: CurrentUser, team_id: str, *, write: bool
) -> TeamAccess:
    if not user.can_read(team_id):
        raise AppError(403, "forbidden", FORBIDDEN_TEAM)
    if (
        user.is_admin
        and await session.scalar(select(m.Team.id).where(m.Team.id == team_id)) is None
    ):
        raise AppError(404, "not_found", "No such team.")
    if write and not user.can_write(team_id):
        raise AppError(403, "forbidden", READ_ONLY)
    return TeamAccess(user, team_id, user.can_write(team_id))


async def require_team_read(team_id: TeamIdPath, user: SignedIn, session: DbSession) -> TeamAccess:
    return await check_team(session, user, team_id, write=False)


async def require_team_write(team_id: TeamIdPath, user: SignedIn, session: DbSession) -> TeamAccess:
    return await check_team(session, user, team_id, write=True)


TeamRead = Annotated[TeamAccess, Depends(require_team_read)]
TeamWrite = Annotated[TeamAccess, Depends(require_team_write)]


async def _resource(
    session: DbSession, user: CurrentUser, team_of: object, resource_id: str, what: str
) -> ResourceAccess:
    team_id = await session.scalar(team_of)  # type: ignore[call-overload]
    if team_id is None:
        raise AppError(404, "not_found", f"No such {what}.")
    access = await check_team(session, user, team_id, write=True)
    return ResourceAccess(access.user, access.team_id, access.can_write, resource_id)


async def require_issue_write(
    issue_id: IssueIdPath, user: SignedIn, session: DbSession
) -> ResourceAccess:
    query = select(m.Issue.team_id).where(m.Issue.id == issue_id)
    return await _resource(session, user, query, issue_id, "Issue")


async def require_todo_write(
    todo_id: TodoIdPath, user: SignedIn, session: DbSession
) -> ResourceAccess:
    query = select(m.Todo.team_id).where(m.Todo.id == todo_id)
    return await _resource(session, user, query, todo_id, "To-Do")


IssueWrite = Annotated[ResourceAccess, Depends(require_issue_write)]
TodoWrite = Annotated[ResourceAccess, Depends(require_todo_write)]


MeetingIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Meeting id, e.g. mt1")]


async def require_meeting_read(
    meeting_id: MeetingIdPath, user: SignedIn, session: DbSession
) -> ResourceAccess:
    """A meeting resolved to its team, then the team-read check. The meeting service adds
    the role rules on top (facilitator, attendee, no ratings from Observers)."""
    team_id = await session.scalar(select(m.Meeting.team_id).where(m.Meeting.id == meeting_id))
    if team_id is None:
        raise AppError(404, "not_found", "No such meeting.")
    access = await check_team(session, user, team_id, write=False)
    return ResourceAccess(access.user, access.team_id, access.can_write, meeting_id)


MeetingRead = Annotated[ResourceAccess, Depends(require_meeting_read)]


async def require_meeting_facilitator(
    meeting_id: MeetingIdPath, user: SignedIn, session: DbSession
) -> ResourceAccess:
    """Advance and end: the meeting's facilitator only, checked before the body is read, so
    nobody else learns anything from validation errors (the service re-checks under lock)."""
    row = (
        await session.execute(
            select(m.Meeting.team_id, m.Meeting.facilitator_id).where(m.Meeting.id == meeting_id)
        )
    ).one_or_none()
    if row is None:
        raise AppError(404, "not_found", "No such meeting.")
    access = await check_team(session, user, row.team_id, write=False)
    if user.id != row.facilitator_id:
        raise AppError(403, "not_facilitator", "Only the facilitator can do that.")
    return ResourceAccess(access.user, access.team_id, access.can_write, meeting_id)


async def require_meeting_rater(
    meeting_id: MeetingIdPath, user: SignedIn, session: DbSession
) -> ResourceAccess:
    """Rating: an Admin or Team Member who can read the team (attendance is checked by the
    service). Observers join meetings but never rate them."""
    access = await require_meeting_read(meeting_id, user, session)
    if user.role == "observer":
        raise AppError(403, "forbidden", "Observers can join meetings but not rate them.")
    return access


MeetingFacilitator = Annotated[ResourceAccess, Depends(require_meeting_facilitator)]
MeetingRater = Annotated[ResourceAccess, Depends(require_meeting_rater)]
