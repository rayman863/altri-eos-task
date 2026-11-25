"""Names of the database rules the API turns into error codes (docs/DB_SCHEMA.md).

The error mapper (Phase 4 on) matches a Postgres error by these names, so they live in one
place; tests/db checks that each one exists in the migrated database, so the code, the
docs and the schema can't drift apart.
"""

# Partial unique indexes and unique constraints (SQLSTATE 23505)
OPEN_ISSUE_FOR_MEASURABLE_WEEK = "ux_issues_open_measurable_week"
OPEN_ISSUE_FOR_ROCK = "ux_issues_open_rock"  # bonus source
OPEN_ISSUE_FOR_TODO = "ux_issues_open_todo"  # bonus source
ONE_ACTIVE_MEETING_PER_TEAM = "ux_meetings_one_active_per_team"
UNIQUE_USER_EMAIL = "uq_users_email"

UNIQUE_NAMES = (
    OPEN_ISSUE_FOR_MEASURABLE_WEEK,
    OPEN_ISSUE_FOR_ROCK,
    OPEN_ISSUE_FOR_TODO,
    ONE_ACTIVE_MEETING_PER_TEAM,
    UNIQUE_USER_EMAIL,
)

# Foreign keys with a rule behind them (SQLSTATE 23503)
RATER_IS_ATTENDEE = "fk_meeting_ratings_attendee"

# Role triggers (SQLSTATE 23514). The constraint name the trigger raises -> its function.
OWNER_ELIGIBLE = "owner_eligible"
FACILITATOR_ELIGIBLE = "facilitator_eligible"
RATER_ELIGIBLE = "rater_eligible"

TRIGGER_FUNCTIONS = {
    OWNER_ELIGIBLE: "eos_check_owner_eligible",
    FACILITATOR_ELIGIBLE: "eos_check_facilitator_eligible",
    RATER_ELIGIBLE: "eos_check_rater_eligible",
}
