"""Request and response models (docs/API_CONTRACTS.md).

Inputs and outputs are separate models, and every input forbids unknown fields, so a client
can never set ids, timestamps, versions or `team_id` (that comes only from the URL path).
Strings are trimmed and length-capped. Decimals go out as strings (`decimal_str`).
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, field_validator

from app.authz import ID_PATTERN

Id = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Priority = Annotated[int, Field(ge=1, le=5, strict=True)]

SCORE_LIMIT = Decimal(1_000_000_000)


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- inputs -------------------------------------------------------------------------------


class Empty(In):
    """Writes without fields still send `{}`."""


class LoginIn(In):
    user_id: Id


class ScoreIn(In):
    value: Decimal = Field(description='A string or a number, e.g. "11" or 4.5')

    @field_validator("value", mode="before")
    @classmethod
    def _exact_decimal(cls, raw: Any) -> Decimal:
        if isinstance(raw, bool) or not isinstance(raw, str | int | float | Decimal):
            raise ValueError("must be a number or a numeric string")
        try:
            value = Decimal(str(raw).strip())
        except InvalidOperation as exc:
            raise ValueError("must be a number") from exc
        if not value.is_finite():
            raise ValueError("must be a finite number")
        if value.as_tuple().exponent < -4:  # type: ignore[operator]
            raise ValueError("at most 4 decimal places")
        if abs(value) > SCORE_LIMIT:
            raise ValueError("absolute value must be at most 1000000000")
        return value


class IssueCreateIn(In):
    title: Title
    priority: Priority | None = None


class IssuePatchIn(In):
    priority: Priority | None = Field(description="1 to 5, or null to clear")


class IssueSolveIn(In):
    resolution_note: Note


class IssueTodoIn(In):
    title: Title
    owner_id: Id


class TodoDoneIn(In):
    done: StrictBool


# ---- outputs ------------------------------------------------------------------------------


class UserRef(Out):
    id: str
    name: str


class TeamRef(Out):
    id: str
    name: str


class SeedUser(Out):
    id: str
    name: str
    email: str
    role: str
    teams: list[TeamRef]


class MeUser(Out):
    id: str
    name: str
    email: str
    role: str


class MeTeam(Out):
    id: str
    name: str
    can_write: bool


class Company(Out):
    id: str
    name: str
    timezone: str


class ClockOut(Out):
    now: datetime
    today: date
    current_week: date
    last_closed_week: date


class Me(Out):
    user: MeUser
    teams: list[MeTeam]
    company: Company
    clock: ClockOut


class TeamListItem(Out):
    id: str
    name: str
    active_meeting_id: str | None


class Member(Out):
    id: str
    name: str
    role: str


class Attendee(Out):
    id: str
    name: str
    role: str
    joined_at: datetime


class Rating(Out):
    user_id: str
    rating: int


class MeetingState(Out):
    id: str
    team_id: str
    status: Literal["active", "ended"]
    section: str
    section_started_at: datetime | None
    section_duration_s: int
    server_now: datetime
    started_at: datetime
    ended_at: datetime | None
    scorecard_week: date
    facilitator: UserRef
    attendees: list[Attendee]
    ratings: list[Rating]
    average_rating: float | None


class TeamDetail(Out):
    id: str
    name: str
    members: list[Member]
    eligible_owners: list[UserRef]
    active_meeting: MeetingState | None


class GoalValue(Out):
    type: Literal["at_least", "at_most", "exactly"]
    value: str


class GoalRange(Out):
    type: Literal["between"]
    min: str
    max: str


Goal = GoalValue | GoalRange


class Cell(Out):
    week_start: date
    value: str | None
    status: Literal["on_track", "off_track", "pending"]
    version: int | None
    open_issue_id: str | None


class MeasurableRow(Out):
    id: str
    name: str
    unit: str
    owner: UserRef
    goal: Goal
    cells: list[Cell]


class Scorecard(Out):
    weeks: list[date]
    current_week: date
    last_closed_week: date
    measurables: list[MeasurableRow]


class IssueSource(Out):
    kind: Literal["measurable_week"]
    measurable_id: str
    measurable_name: str
    week_start: date


class IssueOut(Out):
    id: str
    title: str
    owner: UserRef
    priority: int | None
    created_at: datetime
    solved_at: datetime | None
    resolution_note: str | None
    source: IssueSource | None
    todo_count: int
    version: int


class MadeIssue(Out):
    created: bool
    issue: IssueOut


class SourceIssueRef(Out):
    id: str
    title: str


class TodoOut(Out):
    id: str
    title: str
    owner: UserRef
    due_date: date
    done_at: datetime | None
    overdue: bool
    source_issue: SourceIssueRef | None
    created_at: datetime | None


class WeekCompletion(Out):
    week_start: date
    due: int
    done: int
    rate_percent: int
    meets_target: bool


class TodoList(Out):
    items: list[TodoOut]
    last_closed_week_completion: WeekCompletion | None


class MilestoneOut(Out):
    id: str
    title: str
    due_date: date
    done: bool
    past_due: bool


class RockOut(Out):
    id: str
    title: str
    owner: UserRef
    seeded_status: str
    status: Literal["on_track", "off_track", "complete"]
    progress_percent: int
    milestones: list[MilestoneOut]


class RockList(Out):
    quarter: str
    items: list[RockOut]
