"""Database errors -> API errors (app.errors.map_db_error), without a database.

The API checks every rule itself first, so these paths only run on races or bugs; the
fakes reproduce how SQLAlchemy wraps asyncpg (`exc.orig.__cause__` carries the SQLSTATE and
the constraint name)."""

import pytest
from sqlalchemy import exc as sa_exc

from app import constraints
from app.errors import db_error_info, map_db_error


class FakeAsyncpgError(Exception):
    def __init__(self, sqlstate: str | None, constraint: str | None = None) -> None:
        super().__init__("db error")
        self.sqlstate = sqlstate
        self.constraint_name = constraint


def wrapped(
    cls: type[sa_exc.DBAPIError],
    sqlstate: str | None,
    constraint: str | None = None,
    *,
    invalidated: bool = False,
) -> sa_exc.DBAPIError:
    orig = Exception("driver error")
    orig.__cause__ = FakeAsyncpgError(sqlstate, constraint)
    return cls("SELECT 1", {}, orig, connection_invalidated=invalidated)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            wrapped(sa_exc.IntegrityError, "23514", constraints.OWNER_ELIGIBLE),
            (422, "owner_not_eligible"),
        ),
        (
            wrapped(sa_exc.IntegrityError, "23514", constraints.FACILITATOR_ELIGIBLE),
            (403, "forbidden"),
        ),
        (wrapped(sa_exc.IntegrityError, "23514", constraints.RATER_ELIGIBLE), (403, "forbidden")),
        (
            wrapped(sa_exc.IntegrityError, "23505", constraints.ONE_ACTIVE_MEETING_PER_TEAM),
            (409, "meeting_already_active"),
        ),
        (wrapped(sa_exc.IntegrityError, "23505", "uq_users_email"), (409, "conflict")),
        (wrapped(sa_exc.IntegrityError, "23503", "fk_x"), (409, "conflict")),
        (wrapped(sa_exc.OperationalError, "40001"), (409, "conflict")),
        (wrapped(sa_exc.OperationalError, "40P01"), (409, "conflict")),
        (
            wrapped(sa_exc.IntegrityError, "23514", "ck_issues_title_valid"),
            (422, "validation_failed"),
        ),
        (wrapped(sa_exc.DataError, "22003"), (422, "validation_failed")),
        (wrapped(sa_exc.OperationalError, "57014"), (503, "service_unavailable")),
        (wrapped(sa_exc.OperationalError, "08006"), (503, "service_unavailable")),
        (wrapped(sa_exc.InterfaceError, None), (503, "service_unavailable")),
        (wrapped(sa_exc.DBAPIError, "XX000", invalidated=True), (503, "service_unavailable")),
    ],
)
def test_database_errors_map_to_api_errors(error, expected):
    mapped = map_db_error(error)
    assert mapped is not None
    assert mapped[:2] == expected


@pytest.mark.parametrize("sqlstate", ["XX000", "42P01", None])
def test_unknown_database_errors_stay_500s(sqlstate):
    assert map_db_error(wrapped(sa_exc.ProgrammingError, sqlstate)) is None


def test_constraint_names_come_from_the_asyncpg_cause():
    assert db_error_info(wrapped(sa_exc.IntegrityError, "23505", "uq_users_email")) == (
        "23505",
        "uq_users_email",
    )
