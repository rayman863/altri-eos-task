"""Meeting rules: the rating (brief 2.6) and the summary (brief 2.5, plan 3.9).

The summary's fields match the rules report's meeting format, so the frozen snapshot
written when a meeting ends and the report's live recomputation come from one function.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any
from zoneinfo import ZoneInfo

from app.rules.rounding import round_half_up
from app.rules.scorecard import measurable_status
from app.rules.types import Goal, Issue, Todo
from app.rules.weeks import DEFAULT_TZ, WEEK, week_of


def meeting_rating(ratings: Iterable[int]) -> Decimal | None:
    """Average of the submitted ratings to one decimal, half up. Attendees who didn't
    rate are simply absent from `ratings`. No ratings means no score."""
    values = list(ratings)
    if not values:
        return None
    if any(not 1 <= r <= 10 for r in values):
        raise ValueError("ratings must be between 1 and 10")
    return round_half_up(Fraction(sum(values), len(values)), 1)


def scorecard_week_for(started_at: datetime, tz: ZoneInfo = DEFAULT_TZ) -> date:
    """The week a meeting reviews: the last closed week when it started."""
    return week_of(started_at, tz) - WEEK


@dataclass(frozen=True, slots=True)
class MeetingInput:
    started_at: datetime
    ended_at: datetime
    attendee_ids: Sequence[str]
    ratings: Sequence[int]


def build_meeting_summary(
    meeting: MeetingInput,
    *,
    goals: Mapping[str, Goal],
    scores: Mapping[tuple[str, date], Decimal],
    issues: Iterable[Issue],
    todos: Iterable[Todo],
    tz: ZoneInfo = DEFAULT_TZ,
) -> dict[str, Any]:
    """Summary of an ended meeting, from the team's data (callers pass one team's rows).

    Issues solved and To-Dos created between start and end (inclusive) belong to the
    meeting; the seeded meetings have no explicit links, so attribution is by time."""
    week = scorecard_week_for(meeting.started_at, tz)
    reference_week = week_of(meeting.ended_at, tz)

    def during(ts: datetime | None) -> bool:
        return ts is not None and meeting.started_at <= ts <= meeting.ended_at

    return {
        "scorecard_week": week.isoformat(),
        "measurable_status": {
            mid: measurable_status(goal, scores.get((mid, week)), week, reference_week)
            for mid, goal in sorted(goals.items())
        },
        "issues_solved": sorted(i.id for i in issues if during(i.solved_at)),
        "todos_created": sorted(t.id for t in todos if during(t.created_at)),
        "attendee_ids": sorted(meeting.attendee_ids),
        "rating": meeting_rating(meeting.ratings),
    }
