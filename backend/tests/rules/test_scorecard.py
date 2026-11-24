"""Measurable status: all four goal types at and around their boundaries."""

from datetime import date
from decimal import Decimal

import pytest

from app.rules.scorecard import measurable_status
from app.rules.types import Goal

CURRENT = date(2026, 11, 9)
CLOSED = date(2026, 11, 2)

AT_LEAST_10 = Goal("at_least", value=Decimal(10))
AT_MOST_3 = Goal("at_most", value=Decimal("3.0"))
BETWEEN_2_4 = Goal("between", min=Decimal(2), max=Decimal(4))
EXACTLY_1 = Goal("exactly", value=Decimal(1))


@pytest.mark.parametrize(
    ("goal", "score", "expected"),
    [
        (AT_LEAST_10, "10", "on_track"),  # boundary
        (AT_LEAST_10, "9.99", "off_track"),
        (AT_LEAST_10, "11", "on_track"),
        (AT_MOST_3, "3.0", "on_track"),  # boundary
        (AT_MOST_3, "3", "on_track"),  # same value, different scale
        (AT_MOST_3, "3.01", "off_track"),
        (BETWEEN_2_4, "2", "on_track"),  # lower boundary
        (BETWEEN_2_4, "4", "on_track"),  # upper boundary
        (BETWEEN_2_4, "1.99", "off_track"),
        (BETWEEN_2_4, "4.01", "off_track"),
        (EXACTLY_1, "1", "on_track"),
        (EXACTLY_1, "1.0", "on_track"),
        (EXACTLY_1, "0", "off_track"),
        (EXACTLY_1, "2", "off_track"),
    ],
)
def test_goal_boundaries(goal, score, expected):
    assert measurable_status(goal, Decimal(score), CLOSED, CURRENT) == expected


def test_closed_week_without_score_is_off_track():
    assert measurable_status(AT_LEAST_10, None, CLOSED, CURRENT) == "off_track"


def test_current_week_without_score_is_pending():
    assert measurable_status(AT_LEAST_10, None, CURRENT, CURRENT) == "pending"


def test_current_week_with_score_is_judged_normally():
    assert measurable_status(AT_LEAST_10, Decimal(12), CURRENT, CURRENT) == "on_track"
    assert measurable_status(AT_LEAST_10, Decimal(2), CURRENT, CURRENT) == "off_track"


def test_future_week_has_no_status():
    with pytest.raises(ValueError):
        measurable_status(AT_LEAST_10, None, date(2026, 11, 16), CURRENT)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"type": "between", "min": Decimal(5), "max": Decimal(1)},
        {"type": "between", "min": Decimal(1)},
        {"type": "at_least"},
        {"type": "exactly", "value": Decimal(1), "min": Decimal(0)},
    ],
)
def test_invalid_goal_shapes_are_rejected(kwargs):
    with pytest.raises(ValueError):
        Goal(**kwargs)
