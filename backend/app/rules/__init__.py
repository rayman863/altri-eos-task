"""Business rules of brief section 2.6 as pure functions (plan 3.4).

No database, no clock: every function takes `now` and plain data. The API, the rules
report, meeting snapshots and the tests all call these, so the answers can't drift.
"""

from app.rules.issues import issue_order
from app.rules.meetings import build_meeting_summary, meeting_rating, scorecard_week_for
from app.rules.rocks import rock_progress, rock_status
from app.rules.rounding import percent, round_half_up
from app.rules.scorecard import measurable_status
from app.rules.todos import is_overdue, todo_completion
from app.rules.weeks import (
    current_week,
    last_closed_week,
    today,
    week_bounds,
    week_of,
    week_window,
)

__all__ = [
    "build_meeting_summary",
    "current_week",
    "is_overdue",
    "issue_order",
    "last_closed_week",
    "measurable_status",
    "meeting_rating",
    "percent",
    "rock_progress",
    "rock_status",
    "round_half_up",
    "scorecard_week_for",
    "today",
    "todo_completion",
    "week_bounds",
    "week_of",
    "week_window",
]
