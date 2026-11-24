"""Exact half-up rounding (brief 2.6: 12.5% -> 13%, 8.25 -> 8.3).

Python's round() is banker's rounding (round(12.5) == 12) and floats can't represent
8.25-style midpoints reliably, so everything here is exact Fraction arithmetic.
"""

import math
from decimal import Decimal
from fractions import Fraction

Exact = int | Decimal | Fraction


def round_half_up(value: Exact, places: int = 0) -> Decimal:
    """Round to `places` decimals, halves upward. Returns a Decimal with exactly
    `places` decimals (8.0 stays 8.0)."""
    if isinstance(value, float):
        raise TypeError("floats are not exact; pass int, Decimal or Fraction")
    scaled = Fraction(value) * 10**places
    return Decimal(math.floor(scaled + Fraction(1, 2))).scaleb(-places)


def percent(numerator: int, denominator: int) -> int:
    """numerator / denominator as a whole percent, rounded half up."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return int(round_half_up(Fraction(100 * numerator, denominator)))
