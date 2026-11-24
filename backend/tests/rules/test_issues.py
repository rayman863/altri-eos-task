"""Issue order: priority 5 first, oldest first within a priority, no priority last."""

from app.rules.issues import issue_order
from app.rules.types import Issue
from tests.helpers import utc

NOW = utc("2026-11-11T15:00:00Z")


def issue(iid: str, priority: int | None, created: str, solved: str | None = None) -> Issue:
    return Issue(iid, priority, utc(created), utc(solved) if solved else None)


def test_priority_descending_then_oldest_first_then_no_priority():
    issues = [
        issue("low", 1, "2026-10-01T00:00:00Z"),
        issue("none_old", None, "2026-01-01T00:00:00Z"),
        issue("top_new", 5, "2026-11-01T00:00:00Z"),
        issue("top_old", 5, "2026-10-01T00:00:00Z"),
        issue("mid", 3, "2026-09-01T00:00:00Z"),
    ]
    assert issue_order(issues, NOW) == ["top_old", "top_new", "mid", "low", "none_old"]


def test_no_priority_issues_are_ordered_oldest_first_among_themselves():
    issues = [issue("b", None, "2026-10-02T00:00:00Z"), issue("a", None, "2026-10-01T00:00:00Z")]
    assert issue_order(issues, NOW) == ["a", "b"]


def test_exact_ties_fall_back_to_id_for_a_stable_order():
    same = "2026-10-01T00:00:00Z"
    assert issue_order([issue("i2", 4, same), issue("i10", 4, same)], NOW) == ["i10", "i2"]


def test_solved_issues_are_excluded():
    issues = [
        issue("open", 2, "2026-10-01T00:00:00Z"),
        issue("done", 5, "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z"),
    ]
    assert issue_order(issues, NOW) == ["open"]


def test_as_of_now_creation_and_solving():
    issues = [
        issue("later", 5, "2026-11-20T00:00:00Z"),  # not created yet at NOW
        issue(
            "solved_later", 4, "2026-10-01T00:00:00Z", "2026-11-20T00:00:00Z"
        ),  # still open at NOW
    ]
    assert issue_order(issues, NOW) == ["solved_later"]
