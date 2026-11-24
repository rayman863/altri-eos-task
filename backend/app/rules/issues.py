"""Issue order (brief 2.6): priority 5 first, down to 1; within a priority, oldest first;
no priority comes last. Issue id breaks exact ties so the order is always deterministic.
"""

from collections.abc import Iterable
from datetime import datetime

from app.rules.types import Issue


def unsolved_as_of(issue: Issue, now: datetime) -> bool:
    """Created by now and not yet solved by now."""
    return issue.created_at <= now and (issue.solved_at is None or issue.solved_at > now)


def issue_sort_key(issue: Issue) -> tuple[bool, int, datetime, str]:
    has_no_priority = issue.priority is None
    return (has_no_priority, -(issue.priority or 0), issue.created_at, issue.id)


def issue_order(issues: Iterable[Issue], now: datetime) -> list[str]:
    """Ids of the unsolved Issues, in Issue order."""
    return [i.id for i in sorted((i for i in issues if unsolved_as_of(i, now)), key=issue_sort_key)]
