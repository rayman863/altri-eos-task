"""Lost-update protection (bonus 1, API contracts "Errors" and sections 5 and 7).

A client that wants it sends `If-Match: "<version>"`, the version it last saw (each cell and
each Issue carries one); without the header the brief's rule stands: last save wins. The
service compares under the team lock (`bump_team` comes first in every write), so two
writers can't both pass the check. A mismatch is `409 stale_version` with the current row
in `details.current`, so the client can show what changed instead of overwriting it.

Accepted forms: `"3"`, `3`, `W/"3"`, a comma-separated list (any may match), and `*`
(the row must exist). For a score, version 0 means "no score yet", so a browser that saw
an empty cell sends `"0"` and learns if someone filled it meanwhile.
"""

from typing import Annotated, Any

from fastapi import Header

from app.errors import AppError

ANY = -1  # `*`

IfMatchHeader = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description=(
            'Optional lost-update check: the version you last saw, e.g. "3" (`"0"` for an '
            'empty score cell, `*` for "exists"). A mismatch gives 409 `stale_version`.'
        ),
    ),
]


def expected_versions(raw: str | None) -> frozenset[int] | None:
    """The versions an `If-Match` header accepts (None: no header, no check)."""
    if raw is None or not raw.strip():
        return None
    versions = set()
    for part in raw.split(","):
        tag = part.strip().removeprefix("W/").strip().strip('"')
        if tag == "*":
            versions.add(ANY)
        elif tag.isdigit() and len(tag) <= 10:
            versions.add(int(tag))
        else:
            raise AppError(
                422,
                "validation_failed",
                'If-Match must be a version the API returned, such as "3".',
                details={"fields": [{"loc": ["header", "If-Match"], "msg": "not a version"}]},
            )
    return frozenset(versions)


def accepts(expected: frozenset[int] | None, current: int) -> bool:
    """Whether the header allows the write (`current` 0: the row doesn't exist)."""
    return expected is None or current in expected or (ANY in expected and current > 0)


def stale(current_row: Any, what: str) -> AppError:
    """409 `stale_version`, with the row as it is now."""
    return AppError(
        409,
        "stale_version",
        f"Someone else changed this {what} since you read it; `details.current` holds it as it "
        "is now. Nothing was saved: send the change again with its version if it still applies.",
        details={"current": current_row},
    )


def etag(version: int | None) -> dict[str, str]:
    """The response header carrying the new version, for clients that prefer headers."""
    return {"ETag": f'"{version or 0}"'}
