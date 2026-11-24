"""Rock status and progress."""

from datetime import date

from app.rules.rocks import rock_progress, rock_status
from app.rules.types import Milestone

TODAY = date(2026, 11, 11)


def ms(due: str, done: bool = False, mid: str = "m") -> Milestone:
    return Milestone(mid, date.fromisoformat(due), done)


def test_complete_wins_even_with_past_due_milestones():
    assert rock_status("complete", [ms("2026-11-01")], TODAY) == "complete"


def test_seeded_off_track_stays_off_track():
    assert rock_status("off_track", [], TODAY) == "off_track"


def test_unfinished_milestone_past_due_makes_it_off_track():
    assert rock_status("on_track", [ms("2026-11-10")], TODAY) == "off_track"


def test_milestone_due_today_is_not_past_due():
    assert rock_status("on_track", [ms("2026-11-11")], TODAY) == "on_track"


def test_finished_past_milestone_is_fine():
    assert rock_status("on_track", [ms("2026-10-01", done=True)], TODAY) == "on_track"


def test_no_milestones_uses_seeded_status_alone():
    assert rock_status("on_track", [], TODAY) == "on_track"


def test_progress_is_whole_percent_half_up():
    milestones = [ms("2026-12-01", done=(i == 0), mid=f"m{i}") for i in range(8)]
    assert rock_progress("on_track", milestones) == 13  # 12.5% -> 13


def test_progress_without_milestones():
    assert rock_progress("on_track", []) == 0
    assert rock_progress("off_track", []) == 0
    assert rock_progress("complete", []) == 100


def test_progress_counts_done_milestones():
    assert rock_progress("on_track", [ms("2026-12-01", True), ms("2026-12-02")]) == 50
