"""score_version_seq: score versions that never repeat (lost-update bonus).

`If-Match` on a score compares the version the browser saw with the current one. A score
row is deleted when the score is cleared, so a plain per-row counter would start again at 1
when the score is set again, and a browser still holding "version 1" would match a value it
never saw. Every score write therefore takes its version from this sequence instead.

It starts at 2 because seeded scores (and any score the seed loads) keep the column default,
1, so no app write can ever produce a version a seeded row already has. It is owned by
scores.version, so `TRUNCATE ... RESTART IDENTITY` (`seed --reset`) restarts it with the data.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-28 15:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The default privileges set up by db/init give eos_app USAGE on new sequences.
    op.execute("CREATE SEQUENCE score_version_seq AS integer START WITH 2 OWNED BY scores.version")
    # A database edited before this migration has versions from the old +1 counter: start
    # above all of them, so no write can hand out a version a cell already had.
    op.execute(
        "SELECT setval('score_version_seq', GREATEST(2, (SELECT max(version) + 1 FROM scores)), false)"
    )


def downgrade() -> None:
    op.execute("DROP SEQUENCE score_version_seq")
