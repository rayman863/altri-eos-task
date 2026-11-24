"""Rock status and progress (brief 2.6).

Status: complete if the seeded status is complete; off track if the seeded status is off
track or an unfinished Milestone is past due; otherwise on track. A Milestone due today
is not past due. Progress: completed / total Milestones as a whole percent; with no
Milestones it is 0%, or 100% once complete.
"""

from collections.abc import Sequence
from datetime import date

from app.rules.rounding import percent
from app.rules.types import Milestone, RockStatus


def milestone_past_due(milestone: Milestone, today: date) -> bool:
    return not milestone.done and milestone.due_date < today


def rock_status(
    seeded_status: RockStatus, milestones: Sequence[Milestone], today: date
) -> RockStatus:
    if seeded_status == "complete":
        return "complete"
    if seeded_status == "off_track" or any(milestone_past_due(m, today) for m in milestones):
        return "off_track"
    return "on_track"


def rock_progress(seeded_status: RockStatus, milestones: Sequence[Milestone]) -> int:
    if not milestones:
        return 100 if seeded_status == "complete" else 0
    return percent(sum(1 for m in milestones if m.done), len(milestones))
