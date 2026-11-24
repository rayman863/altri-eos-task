"""Half-up rounding (brief 2.6: 12.5% -> 13%, 8.25 -> 8.3)."""

from decimal import Decimal
from fractions import Fraction

import pytest

from app.rules.rounding import percent, round_half_up


def test_brief_examples():
    assert round_half_up(Decimal("12.5")) == Decimal(13)
    assert round_half_up(Decimal("8.25"), 1) == Decimal("8.3")


def test_python_round_would_get_these_wrong():
    # The reason this module exists: banker's rounding goes to the even neighbour.
    assert round(12.5) == 12
    assert round(8.25, 1) == 8.2


def test_just_below_half_rounds_down():
    assert round_half_up(Decimal("8.24"), 1) == Decimal("8.2")
    assert round_half_up(Fraction(1249, 100)) == Decimal(12)


def test_keeps_one_decimal_for_whole_numbers():
    assert str(round_half_up(Fraction(24, 3), 1)) == "8.0"


@pytest.mark.parametrize(
    ("numerator", "denominator", "expected"),
    [
        (1, 8, 13),  # 12.5 -> 13
        (9, 10, 90),
        (2, 3, 67),  # 66.67
        (1, 3, 33),  # 33.33
        (0, 4, 0),
        (5, 5, 100),
    ],
)
def test_percent(numerator, denominator, expected):
    assert percent(numerator, denominator) == expected


def test_percent_needs_a_positive_denominator():
    with pytest.raises(ValueError):
        percent(1, 0)


def test_floats_are_refused():
    with pytest.raises(TypeError):
        round_half_up(8.25, 1)  # type: ignore[arg-type]
