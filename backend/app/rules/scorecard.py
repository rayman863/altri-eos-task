"""Measurable status (brief 2.6): compare the week's score with the goal.

Boundaries are on track. A closed week with no score is off track; the current week
with no score is pending.
"""

from datetime import date
from decimal import Decimal

from app.rules.types import Goal, MeasurableStatus


def meets_goal(goal: Goal, score: Decimal) -> bool:
    match goal.type:
        case "at_least":
            return score >= goal.value  # type: ignore[operator]
        case "at_most":
            return score <= goal.value  # type: ignore[operator]
        case "between":
            return goal.min <= score <= goal.max  # type: ignore[operator]
        case "exactly":
            return score == goal.value
    raise ValueError(f"unknown goal type {goal.type!r}")


def measurable_status(
    goal: Goal, score: Decimal | None, week_start: date, current_week: date
) -> MeasurableStatus:
    if week_start > current_week:
        raise ValueError("a week after the current week has no status")
    if score is None:
        return "pending" if week_start == current_week else "off_track"
    return "on_track" if meets_goal(goal, score) else "off_track"
