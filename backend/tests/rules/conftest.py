"""Loads seed/seed.json into the rules' plain types, for the oracle tests (plan section 4)."""

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.rules.meetings import MeetingInput
from app.rules.types import Goal, Issue, Milestone, Todo
from tests.helpers import utc

_REPO_SEED = Path(__file__).resolve().parents[3] / "seed" / "seed.json"


def _seed_path() -> Path:
    env = os.environ.get("SEED_PATH")
    return Path(env) if env else _REPO_SEED


def _dt(value: str | None) -> datetime | None:
    return utc(value) if value else None


def _goal(raw: dict[str, Any]) -> Goal:
    if raw["type"] == "between":
        return Goal("between", min=Decimal(raw["min"]), max=Decimal(raw["max"]))
    return Goal(raw["type"], value=Decimal(raw["value"]))


@dataclass
class Seed:
    now: datetime
    measurable_team: dict[str, str] = field(default_factory=dict)
    goals: dict[str, Goal] = field(default_factory=dict)
    scores: dict[tuple[str, date], Decimal] = field(default_factory=dict)
    todos: dict[str, list[Todo]] = field(default_factory=dict)
    issues: dict[str, list[Issue]] = field(default_factory=dict)
    rocks: dict[str, tuple[str, str, list[Milestone]]] = field(default_factory=dict)
    meetings: dict[str, tuple[str, MeetingInput]] = field(default_factory=dict)

    def team_goals(self, team_id: str) -> dict[str, Goal]:
        return {m: g for m, g in self.goals.items() if self.measurable_team[m] == team_id}


@pytest.fixture(scope="session")
def seed() -> Seed:
    # Floats parse as Decimal so goals like 3.0 and scores like 4.1 stay exact.
    raw = json.loads(_seed_path().read_text(encoding="utf-8"), parse_float=Decimal)
    data = Seed(now=utc(raw["meta"]["now"]))
    for m in raw["measurables"]:
        data.measurable_team[m["id"]] = m["team_id"]
        data.goals[m["id"]] = _goal(m["goal"])
    for s in raw["scores"]:
        data.scores[(s["measurable_id"], date.fromisoformat(s["week_start"]))] = Decimal(s["value"])
    for t in raw["todos"]:
        data.todos.setdefault(t["team_id"], []).append(
            Todo(
                id=t["id"],
                due_date=date.fromisoformat(t["due_date"]),
                done_at=_dt(t["done_at"]),
                created_at=_dt(t["created_at"]),
            )
        )
    for i in raw["issues"]:
        data.issues.setdefault(i["team_id"], []).append(
            Issue(
                id=i["id"],
                priority=i["priority"],
                created_at=utc(i["created_at"]),
                solved_at=_dt(i["solved_at"]),
            )
        )
    milestones: dict[str, list[Milestone]] = {}
    for ms in raw["milestones"]:
        milestones.setdefault(ms["rock_id"], []).append(
            Milestone(id=ms["id"], due_date=date.fromisoformat(ms["due_date"]), done=ms["done"])
        )
    for r in raw["rocks"]:
        data.rocks[r["id"]] = (r["team_id"], r["status"], milestones.get(r["id"], []))
    for mt in raw["meetings"]:
        data.meetings[mt["id"]] = (
            mt["team_id"],
            MeetingInput(
                started_at=utc(mt["started_at"]),
                ended_at=utc(mt["ended_at"]),
                attendee_ids=mt["attendee_ids"],
                ratings=[r["rating"] for r in mt["ratings"]],
            ),
        )
    return data
