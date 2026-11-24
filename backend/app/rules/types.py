"""Plain data the rules work on. No ORM, no I/O: callers (API, rules report, snapshots,
tests) map their rows into these."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

GoalType = Literal["at_least", "at_most", "between", "exactly"]
MeasurableStatus = Literal["on_track", "off_track", "pending"]
RockStatus = Literal["on_track", "off_track", "complete"]


@dataclass(frozen=True, slots=True)
class Goal:
    type: GoalType
    value: Decimal | None = None
    min: Decimal | None = None
    max: Decimal | None = None

    def __post_init__(self) -> None:
        if self.type == "between":
            if self.min is None or self.max is None or self.value is not None:
                raise ValueError("a 'between' goal needs min and max, and no value")
            if self.min > self.max:
                raise ValueError("goal min must not exceed max")
        elif self.value is None or self.min is not None or self.max is not None:
            raise ValueError(f"a '{self.type}' goal needs a value, and no min/max")


@dataclass(frozen=True, slots=True)
class Todo:
    id: str
    due_date: date
    done_at: datetime | None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Milestone:
    id: str
    due_date: date
    done: bool


@dataclass(frozen=True, slots=True)
class Issue:
    id: str
    priority: int | None
    created_at: datetime
    solved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Completion:
    due: int
    done: int
    rate_percent: int
    meets_target: bool
