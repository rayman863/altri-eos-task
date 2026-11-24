"""The one error body shape (docs/API_CONTRACTS.md, section 1). No app imports here, so both
the error handlers and the logging middleware can use it without an import cycle."""

from typing import Any


def error_body(
    code: str,
    message: str,
    request_id: str | None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
        }
    }


INTERNAL_ERROR_MESSAGE = "Something went wrong. Quote the request_id when reporting it."
