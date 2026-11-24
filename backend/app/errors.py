"""One error envelope for every failure (docs/API_CONTRACTS.md, section 1).

{"error": {"code", "message", "details", "request_id"}}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Last resort only: RequestLogMiddleware normally answers unhandled errors itself,
        # with the request id (this handler runs outside it, where the id is gone).
        # Full traceback goes to the logs (Dozzle), never to the client.
        log.error("unhandled error", exc_info=exc)
        return error_response(500, "internal_error", INTERNAL_ERROR_MESSAGE)
