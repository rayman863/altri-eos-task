"""users.session_epoch: logout ends every session of the user (Phase 4 review).

The session cookie is a signed token, so the server can't delete it. Each token carries the
user's epoch at login; logout bumps the epoch, and tokens from an older epoch are refused.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-26 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("session_epoch", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "session_epoch")
