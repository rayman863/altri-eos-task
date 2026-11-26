"""One error envelope for every failure (docs/API_CONTRACTS.md, section 1).

{"error": {"code", "message", "details", "request_id"}}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import exc as sa_exc
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import constraints
from app.envelope import INTERNAL_ERROR_MESSAGE, error_body
from app.logging import request_id_var

log = logging.getLogger("eos.errors")

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_failed",
    429: "rate_limited",
    503: "service_unavailable",
}


class AppError(Exception):
    """Raised by app code for any expected failure with a named code."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_response(
    status: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=error_body(code, message, request_id_var.get(), details),
        headers=headers,
    )


def db_error_info(exc: sa_exc.DBAPIError) -> tuple[str | None, str | None]:
    """(SQLSTATE, constraint name) of a Postgres error raised through asyncpg."""
    orig = exc.orig
    cause = getattr(orig, "__cause__", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(cause, "sqlstate", None)
    constraint = getattr(cause, "constraint_name", None) or getattr(orig, "constraint_name", None)
    return sqlstate, constraint


def map_db_error(exc: sa_exc.DBAPIError) -> tuple[int, str, str] | None:
    """The API answer for a rule the database enforced (the API checks first, so these are
    races or bugs). Names come from app.constraints, so they can't drift from the schema."""
    sqlstate, constraint = db_error_info(exc)
    if constraint == constraints.OWNER_ELIGIBLE:
        return 422, "owner_not_eligible", "That person can't own items in this team."
    if constraint in (constraints.FACILITATOR_ELIGIBLE, constraints.RATER_ELIGIBLE):
        return 403, "forbidden", "Your role can't do that in this meeting."
    if constraint == constraints.ONE_ACTIVE_MEETING_PER_TEAM:
        return 409, "meeting_already_active", "This team already has an active meeting."
    if exc.connection_invalidated or (
        sqlstate is None and isinstance(exc, sa_exc.OperationalError | sa_exc.InterfaceError)
    ):
        # The connection died (database restart, network): retryable, not a server bug.
        return 503, "service_unavailable", "The database connection was lost. Try again."
    if sqlstate is None:
        return None
    if sqlstate.startswith("08"):  # connection exception class
        return 503, "service_unavailable", "The database connection was lost. Try again."
    if sqlstate in ("23505", "23503", "40001", "40P01"):
        # unique / foreign key / serialization / deadlock: someone else changed it first
        return 409, "conflict", "That change conflicts with another one. Reload and try again."
    if sqlstate == "23514" or sqlstate.startswith("22"):  # check violation, bad data
        return 422, "validation_failed", "The database rejected a value."
    if sqlstate == "57014":  # statement timeout
        return 503, "service_unavailable", "The database took too long. Try again."
    return None


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        if any(e.get("type") == "json_invalid" for e in errors):
            return error_response(400, "bad_request", "Malformed JSON body.")
        fields = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", "Invalid value")} for e in errors
        ]
        return error_response(
            422, "validation_failed", "Request validation failed.", {"fields": fields}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "error")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ")
        return error_response(exc.status_code, code, message, headers=exc.headers)

    @app.exception_handler(sa_exc.TimeoutError)
    async def _pool_timeout(_: Request, exc: sa_exc.TimeoutError) -> JSONResponse:
        log.warning("no database connection free", exc_info=exc)
        return error_response(
            503, "db_busy", "The database is busy. Try again.", headers={"Retry-After": "1"}
        )

    @app.exception_handler(sa_exc.DBAPIError)
    async def _database(_: Request, exc: sa_exc.DBAPIError) -> JSONResponse:
        mapped = map_db_error(exc)
        if mapped is None:
            log.error("unhandled database error", exc_info=exc)
            return error_response(500, "internal_error", INTERNAL_ERROR_MESSAGE)
        status, code, message = mapped
        log.info("database refused a change", extra={"code": code, "error": str(exc.orig)})
        return error_response(status, code, message)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Last resort only: RequestLogMiddleware normally answers unhandled errors itself,
        # with the request id (this handler runs outside it, where the id is gone).
        # Full traceback goes to the logs (Dozzle), never to the client.
        log.error("unhandled error", exc_info=exc)
        return error_response(500, "internal_error", INTERNAL_ERROR_MESSAGE)
