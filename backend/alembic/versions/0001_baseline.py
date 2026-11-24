"""Baseline: empty revision so `alembic upgrade head` works before the schema exists.

The real schema (docs/DB_SCHEMA.md) is added in Phase 2 as the next revision.

Revision ID: 0001
Revises:
Create Date: 2026-11-25
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
