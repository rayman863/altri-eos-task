"""One JSON encoding for values the rules produce (meeting snapshots, the rules report).

- Decimal -> JSON number. Ratings are already rounded to one decimal, so 8.25 arrives as
  Decimal("8.3") and is written as 8.3; Decimal("8.0") is written as 8.0. That is right
  for ratings only: API scores and goals are strings (docs/API_CONTRACTS.md "Decimals"),
  so API payloads format them with `decimal_str` before encoding.
- date -> "YYYY-MM-DD"; aware datetime -> ISO 8601 in UTC with "Z".
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise TypeError(f"naive datetime can't be encoded: {value!r}")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def decimal_str(value: Decimal) -> str:
    """A score or goal as the API sends it: exact, shortest form, no exponent.

    NUMERIC(14,4) columns come back as Decimal("8.0000"); this gives "8". Decimal("4.1000")
    gives "4.1", Decimal("100.0000") gives "100" (not "1E+2"), and -0 gives "0"."""
    if not value.is_finite():
        raise ValueError(f"not a finite decimal: {value!r}")
    if value.is_zero():
        return "0"
    return format(value.normalize(), "f")


def to_jsonable(value: Any) -> Any:
    """Plain JSON types only (for asyncpg jsonb parameters and rule documents). Decimals
    become numbers; run API scores and goals through `decimal_str` first."""
    return json.loads(dumps(value))


def dumps(value: Any, **kwargs: Any) -> str:
    return json.dumps(value, default=_default, ensure_ascii=False, **kwargs)
