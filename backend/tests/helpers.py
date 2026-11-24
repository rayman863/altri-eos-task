"""Small helpers shared by the test suites."""

from datetime import UTC, datetime


def utc(value: str) -> datetime:
    """'2026-11-09T05:59:00Z' -> aware UTC datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
