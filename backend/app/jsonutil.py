"""One JSON encoding for values the rules produce (meeting snapshots, the rules report).

- Decimal -> JSON number. Ratings are already rounded to one decimal, so 8.25 arrives as
  Decimal("8.3") and is written as 8.3; Decimal("8.0") is written as 8.0.
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


def to_jsonable(value: Any) -> Any:
    """Plain JSON types only (for asyncpg jsonb parameters and API responses)."""
    return json.loads(dumps(value))


def dumps(value: Any, **kwargs: Any) -> str:
    return json.dumps(value, default=_default, ensure_ascii=False, **kwargs)
