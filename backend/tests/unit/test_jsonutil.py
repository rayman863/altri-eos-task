"""JSON encoding of rule outputs (meeting snapshots, rules report)."""

import json
from datetime import date
from decimal import Decimal

import pytest

from app.jsonutil import dumps, to_jsonable
from tests.helpers import utc


def test_ratings_keep_one_decimal():
    assert dumps({"rating": Decimal("8.3")}) == '{"rating": 8.3}'
    assert dumps({"rating": Decimal("8.0")}) == '{"rating": 8.0}'


def test_dates_and_datetimes():
    encoded = json.loads(dumps({"d": date(2026, 11, 2), "t": utc("2026-11-04T15:00:00Z")}))
    assert encoded == {"d": "2026-11-02", "t": "2026-11-04T15:00:00Z"}


def test_to_jsonable_returns_plain_types():
    assert to_jsonable({"rating": Decimal("8.3"), "ids": ["i6"]}) == {"rating": 8.3, "ids": ["i6"]}


def test_naive_datetimes_and_unknown_types_fail_loudly():
    from datetime import datetime

    with pytest.raises(TypeError):
        dumps(datetime(2026, 1, 1))  # noqa: DTZ001
    with pytest.raises(TypeError):
        dumps(object())
