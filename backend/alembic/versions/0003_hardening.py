"""Hardening after the Phase 2 review:
- partial unique indexes for open Issues raised from a Rock or a To-Do (the bonus
  sources already allowed by ck_issues_source_consistent), matching
  ux_issues_open_measurable_week;
- the role trigger functions pin `search_path`, so an unqualified `users` or
  `memberships` can never resolve to another schema's table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-25 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPEN_ISSUE_INDEXES = [
    ("ux_issues_open_rock", "source_rock_id", "rock"),
    ("ux_issues_open_todo", "source_todo_id", "todo"),
]
TRIGGER_FUNCTIONS = [
    "eos_check_owner_eligible",
    "eos_check_facilitator_eligible",
    "eos_check_rater_eligible",
]


def upgrade() -> None:
    for name, column, kind in OPEN_ISSUE_INDEXES:
        op.create_index(
            name,
            "issues",
            [column],
            unique=True,
            postgresql_where=sa.text(f"solved_at IS NULL AND source_kind = '{kind}'"),
        )
    for function in TRIGGER_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function}() SET search_path = public, pg_temp")


def downgrade() -> None:
    for function in TRIGGER_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function}() RESET search_path")
    for name, _, kind in reversed(OPEN_ISSUE_INDEXES):
        op.drop_index(
            name,
            table_name="issues",
            postgresql_where=sa.text(f"solved_at IS NULL AND source_kind = '{kind}'"),
        )
