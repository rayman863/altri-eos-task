"""Database schema (docs/DB_SCHEMA.md). Constraints live here so the database itself
rejects invalid data (brief 2.7 "Data integrity"); role rules that a foreign key can't
express are triggers in the migration.

Bonus objects (activity_outbox, the Rock/To-Do Issue-source unique indexes) are not here.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


TS = DateTime(timezone=True)  # always UTC instants
SCORE = Numeric(14, 4)  # scores and goals: exact decimals, never floats

ROLES = ("admin", "team_member", "observer")
GOAL_TYPES = ("at_least", "at_most", "between", "exactly")
ROCK_STATUSES = ("on_track", "off_track", "complete")
SECTIONS = ("scorecard", "ids", "conclude")
SOURCE_KINDS = ("measurable_week", "rock", "todo")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def id_format() -> CheckConstraint:
    return CheckConstraint("id ~ '^[a-z0-9_]{1,64}$'", name="id_format")


def text_field(column: str, max_length: int) -> CheckConstraint:
    return CheckConstraint(
        f"btrim({column}) <> '' AND char_length({column}) <= {max_length}",
        name=f"{column}_valid",
    )


def monday(column: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} IS NULL OR extract(isodow FROM {column}) = 1", name=f"{column}_monday"
    )


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        id_format(),
        text_field("name", 200),
        CheckConstraint("btrim(timezone) <> ''", name="timezone_set"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        id_format(),
        text_field("name", 200),
        CheckConstraint(_in("role", ROLES), name="role_valid"),
        CheckConstraint("email ~ '^[^@\\s]+@[^@\\s]+$'", name="email_format"),
        UniqueConstraint("email"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (id_format(), text_field("name", 200))

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(Text)
    # Bumped as the FIRST statement of every team-scoped write (plan 3.14): cache key
    # version, and a consistent lock order so concurrent team writes can't deadlock.
    cache_version: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (Index("ix_memberships_team_id", "team_id"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), primary_key=True)


class Measurable(Base):
    __tablename__ = "measurables"
    __table_args__ = (
        id_format(),
        text_field("name", 200),
        CheckConstraint("char_length(unit) <= 20", name="unit_length"),
        CheckConstraint(_in("goal_type", GOAL_TYPES), name="goal_type_valid"),
        CheckConstraint(
            "(goal_type = 'between' AND goal_min IS NOT NULL AND goal_max IS NOT NULL"
            " AND goal_value IS NULL AND goal_min <= goal_max)"
            " OR (goal_type <> 'between' AND goal_value IS NOT NULL"
            " AND goal_min IS NULL AND goal_max IS NULL)",
            name="goal_shape",
        ),
        UniqueConstraint("id", "team_id"),
        Index("ix_measurables_team_id", "team_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(Text)
    goal_type: Mapped[str] = mapped_column(Text)
    goal_value: Mapped[Decimal | None] = mapped_column(SCORE)
    goal_min: Mapped[Decimal | None] = mapped_column(SCORE)
    goal_max: Mapped[Decimal | None] = mapped_column(SCORE)


class Score(Base):
    __tablename__ = "scores"
    __table_args__ = (
        monday("week_start"),
        CheckConstraint("abs(value) <= 1000000000", name="value_range"),
    )

    measurable_id: Mapped[str] = mapped_column(ForeignKey("measurables.id"), primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal] = mapped_column(SCORE)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime | None] = mapped_column(TS)  # null for seeded scores


class Rock(Base):
    __tablename__ = "rocks"
    __table_args__ = (
        id_format(),
        text_field("title", 200),
        CheckConstraint("quarter ~ '^[0-9]{4}-Q[1-4]$'", name="quarter_format"),
        CheckConstraint(_in("status", ROCK_STATUSES), name="status_valid"),
        UniqueConstraint("id", "team_id"),
        Index("ix_rocks_team_id_quarter", "team_id", "quarter"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(Text)
    quarter: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)  # the seeded status; the rules compute the shown one


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (
        id_format(),
        text_field("title", 200),
        Index("ix_milestones_rock_id", "rock_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    rock_id: Mapped[str] = mapped_column(ForeignKey("rocks.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date] = mapped_column(Date)
    done: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (
        id_format(),
        text_field("title", 200),
        CheckConstraint("priority IS NULL OR priority BETWEEN 1 AND 5", name="priority_range"),
        CheckConstraint(
            # resolution_note IS NOT NULL is required: with a NULL note, btrim(...) <> ''
            # is NULL, and a CHECK that evaluates to NULL passes.
            "(solved_at IS NULL AND resolution_note IS NULL AND solved_by IS NULL)"
            " OR (solved_at IS NOT NULL AND resolution_note IS NOT NULL"
            " AND btrim(resolution_note) <> '' AND char_length(resolution_note) <= 2000)",
            name="solved_consistent",
        ),
        CheckConstraint(
            "(source_kind IS NULL AND source_measurable_id IS NULL"
            " AND source_week_start IS NULL AND source_rock_id IS NULL AND source_todo_id IS NULL)"
            " OR (source_kind = 'measurable_week' AND source_measurable_id IS NOT NULL"
            " AND source_week_start IS NOT NULL AND source_rock_id IS NULL"
            " AND source_todo_id IS NULL)"
            " OR (source_kind = 'rock' AND source_rock_id IS NOT NULL"
            " AND source_measurable_id IS NULL AND source_week_start IS NULL"
            " AND source_todo_id IS NULL)"
            " OR (source_kind = 'todo' AND source_todo_id IS NOT NULL"
            " AND source_measurable_id IS NULL AND source_week_start IS NULL"
            " AND source_rock_id IS NULL)",
            name="source_consistent",
        ),
        monday("source_week_start"),
        UniqueConstraint("id", "team_id"),
        # Same-team links: an Issue's source always belongs to the Issue's team.
        ForeignKeyConstraint(
            ["source_measurable_id", "team_id"],
            ["measurables.id", "measurables.team_id"],
            name="fk_issues_source_measurable_same_team",
        ),
        ForeignKeyConstraint(
            ["source_rock_id", "team_id"],
            ["rocks.id", "rocks.team_id"],
            name="fk_issues_source_rock_same_team",
        ),
        ForeignKeyConstraint(
            ["source_todo_id", "team_id"],
            ["todos.id", "todos.team_id"],
            name="fk_issues_source_todo_same_team",
            use_alter=True,  # issues <-> todos reference each other
        ),
        # No duplicate open Issues per Measurable and week, even under concurrent clicks
        # (brief 2.6, plan 3.8).
        Index(
            "ux_issues_open_measurable_week",
            "source_measurable_id",
            "source_week_start",
            unique=True,
            postgresql_where=text("solved_at IS NULL AND source_kind = 'measurable_week'"),
        ),
        Index("ix_issues_team_id_solved_at", "team_id", "solved_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(Text)
    priority: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(TS)
    solved_at: Mapped[datetime | None] = mapped_column(TS)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    solved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    source_kind: Mapped[str | None] = mapped_column(Text)
    source_measurable_id: Mapped[str | None] = mapped_column(Text)
    source_week_start: Mapped[date | None] = mapped_column(Date)
    source_rock_id: Mapped[str | None] = mapped_column(Text)
    source_todo_id: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class Todo(Base):
    __tablename__ = "todos"
    __table_args__ = (
        id_format(),
        text_field("title", 200),
        UniqueConstraint("id", "team_id"),
        ForeignKeyConstraint(
            ["source_issue_id", "team_id"],
            ["issues.id", "issues.team_id"],
            name="fk_todos_source_issue_same_team",
        ),
        Index("ix_todos_team_id_due_date", "team_id", "due_date"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date] = mapped_column(Date)
    done_at: Mapped[datetime | None] = mapped_column(TS)
    source_issue_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS)


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        id_format(),
        CheckConstraint(_in("section", SECTIONS), name="section_valid"),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ends_after_start"),
        monday("scorecard_week"),
        # One active meeting per team (brief 2.5).
        Index(
            "ux_meetings_one_active_per_team",
            "team_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        Index("ix_meetings_team_id_ended_at", "team_id", "ended_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    facilitator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(TS)
    ended_at: Mapped[datetime | None] = mapped_column(TS)
    section: Mapped[str] = mapped_column(Text)
    section_started_at: Mapped[datetime | None] = mapped_column(TS)  # null for seeded meetings
    scorecard_week: Mapped[date] = mapped_column(Date)


class MeetingAttendee(Base):
    __tablename__ = "meeting_attendees"

    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(TS)


class MeetingRating(Base):
    __tablename__ = "meeting_ratings"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 10", name="rating_range"),
        # Only attendees can rate.
        ForeignKeyConstraint(
            ["meeting_id", "user_id"],
            ["meeting_attendees.meeting_id", "meeting_attendees.user_id"],
            name="fk_meeting_ratings_attendee",
            ondelete="CASCADE",
        ),
    )

    meeting_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rating: Mapped[int] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime | None] = mapped_column(TS)


class MeetingSummary(Base):
    """Frozen when a meeting ends (plan 3.9); never recomputed."""

    __tablename__ = "meeting_summaries"

    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True
    )
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TS)


class ClockAnchor(Base):
    """Shared origin of the ticking clock for every API worker (plan 3.2); used from Phase 5."""

    __tablename__ = "clock_anchor"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
    app_now: Mapped[datetime] = mapped_column(TS)
    real_now: Mapped[datetime] = mapped_column(TS)
