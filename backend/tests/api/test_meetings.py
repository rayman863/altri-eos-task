"""Level 10 Meeting commands and the frozen summary (plan 3.7 and 3.9, API contracts 9)."""

from datetime import timedelta

import pytest

START = "/teams/team_lead/meetings"


@pytest.fixture
def meeting(login):
    """An active Leadership meeting facilitated by u3. Returns (facilitator client, state)."""
    facilitator = login("u3")
    resp = facilitator.post(START)
    assert resp.status == 201, resp.body
    return facilitator, resp.body


def tick(app, **delta):
    app.state.clock.advance(timedelta(**delta))


# ---- start ----------------------------------------------------------------------------------


def test_start_makes_the_caller_facilitator_and_first_attendee(meeting):
    _, state = meeting
    assert state["id"].startswith("mt_")
    assert {k: state[k] for k in ("team_id", "status", "section", "section_duration_s")} == {
        "team_id": "team_lead",
        "status": "active",
        "section": "scorecard",
        "section_duration_s": 300,
    }
    assert state["facilitator"] == {"id": "u3", "name": "Casey Cho"}
    assert [a["id"] for a in state["attendees"]] == ["u3"]
    assert (
        state["started_at"]
        == state["section_started_at"]
        == state["server_now"]
        == "2026-11-11T15:00:00Z"
    )
    assert state["scorecard_week"] == "2026-11-02"  # the last closed week
    assert (state["ended_at"], state["ratings"], state["average_rating"]) == (None, [], None)


def test_only_one_active_meeting_per_team(meeting, login):
    _, state = meeting
    resp = login("u2").post(START)
    assert (resp.status, resp.error) == (409, "meeting_already_active")
    assert resp.body["error"]["details"] == {"meeting_id": state["id"]}


def test_the_active_meeting_shows_everywhere(meeting, login):
    _, state = meeting
    reader = login("u5")
    assert reader.get("/teams/team_lead/meetings/active").body["meeting"]["id"] == state["id"]
    assert reader.get("/teams/team_lead").body["active_meeting"]["id"] == state["id"]
    assert reader.get("/teams").body[0]["active_meeting_id"] == state["id"]
    assert reader.get(f"/meetings/{state['id']}").body["section"] == "scorecard"
    assert login("u6").get("/teams/team_sales/meetings/active").body == {"meeting": None}


# ---- join -----------------------------------------------------------------------------------


def test_anyone_who_can_read_the_team_joins_once(app, meeting, login):
    _, state = meeting
    observer = login("u5")
    tick(app, minutes=1)
    first = observer.post(f"/meetings/{state['id']}/join")
    assert first.status == 200
    joined = {a["id"]: a for a in first.body["attendees"]}
    assert joined["u5"] == {
        "id": "u5",
        "name": "Ellis Evans",
        "role": "observer",
        "joined_at": "2026-11-11T15:01:00Z",
    }
    tick(app, minutes=5)
    again = observer.post(f"/meetings/{state['id']}/join")
    assert {a["id"]: a for a in again.body["attendees"]}["u5"][
        "joined_at"
    ] == "2026-11-11T15:01:00Z"


# ---- advance --------------------------------------------------------------------------------


def test_facilitator_advances_forward_one_section_at_a_time(app, meeting, login):
    facilitator, state = meeting
    path = f"/meetings/{state['id']}/advance"
    other = login("u2")
    other.post(f"/meetings/{state['id']}/join")
    assert other.post(path, {"expected_section": "scorecard"}).error == "not_facilitator"

    tick(app, minutes=6)
    ids = facilitator.post(path, {"expected_section": "scorecard"})
    assert ids.status == 200
    assert (
        ids.body["section"],
        ids.body["section_started_at"],
        ids.body["section_duration_s"],
    ) == (
        "ids",
        "2026-11-11T15:06:00Z",
        3600,
    )
    # A double click (stale expected_section) can't skip a section.
    stale = facilitator.post(path, {"expected_section": "scorecard"})
    assert (stale.status, stale.error, stale.body["error"]["details"]) == (
        409,
        "section_changed",
        {"section": "ids"},
    )
    assert facilitator.post(path, {"expected_section": "ids"}).body["section"] == "conclude"
    last = facilitator.post(path, {"expected_section": "conclude"})
    assert (last.status, last.error) == (409, "last_section")
    assert facilitator.post(path, {"expected_section": "lunch"}).error == "validation_failed"


# ---- rating ---------------------------------------------------------------------------------


def test_rating_rules(meeting, login):
    facilitator, state = meeting
    path = f"/meetings/{state['id']}/rating"
    observer = login("u5")
    observer.post(f"/meetings/{state['id']}/join")
    assert observer.put(path, {"rating": 8}).error == "forbidden"
    assert login("u4").put(path, {"rating": 8}).error == "not_attendee"  # never joined
    assert facilitator.put(path, {"rating": 8}).body == {"user_id": "u3", "rating": 8}
    assert facilitator.put(path, {"rating": 9}).status == 200  # changeable until the end
    member = login("u2")
    member.post(f"/meetings/{state['id']}/join")
    member.put(path, {"rating": 8})
    current = facilitator.get(f"/meetings/{state['id']}").body
    assert current["ratings"] == [{"user_id": "u2", "rating": 8}, {"user_id": "u3", "rating": 9}]
    assert current["average_rating"] == 8.5
    for bad in (0, 11, "8", 7.5, None):
        assert facilitator.put(path, {"rating": bad}).error == "validation_failed", bad


# ---- end and summary ------------------------------------------------------------------------


def test_end_freezes_a_summary_that_later_edits_cannot_change(app, meeting, login):
    facilitator, state = meeting
    mid = state["id"]
    assert facilitator.get(f"/meetings/{mid}/summary").error == "meeting_not_ended"
    member = login("u2")
    member.post(f"/meetings/{mid}/join")
    tick(app, minutes=10)
    # During the meeting: solve an Issue, add a follow-up To-Do, rate.
    assert (
        facilitator.post("/issues/i1/solve", {"resolution_note": "Hired a recruiter."}).status
        == 200
    )
    todo = facilitator.post(
        "/issues/i1/todos", {"title": "Brief the recruiter", "owner_id": "u2"}
    ).body
    facilitator.put(f"/meetings/{mid}/rating", {"rating": 9})
    member.put(f"/meetings/{mid}/rating", {"rating": 8})
    assert member.post(f"/meetings/{mid}/end").error == "not_facilitator"

    tick(app, minutes=50)
    ended = facilitator.post(f"/meetings/{mid}/end")
    assert ended.status == 200
    assert (ended.body["status"], ended.body["ended_at"]) == ("ended", "2026-11-11T16:00:00Z")

    summary = facilitator.get(f"/meetings/{mid}/summary").body
    assert summary["scorecard_week"] == "2026-11-02"
    assert summary["measurable_status"] == {
        "m1": "off_track",  # 8, goal >= 10
        "m2": "on_track",
        "m3": "off_track",  # 4.5, goal 2..4
        "m4": "on_track",
        "m5": "off_track",  # no score
    }
    assert (summary["issues_solved"], summary["todos_created"]) == (["i1"], [todo["id"]])
    assert (summary["attendee_ids"], summary["rating"]) == (["u2", "u3"], 8.5)
    assert summary["labels"]["issues"] == {"i1": "Hiring pipeline is slow"}

    # Later edits: the score that was off track, and the solved Issue's follow-up.
    tick(app, hours=1)
    facilitator.put("/teams/team_lead/measurables/m1/scores/2026-11-02", {"value": 12})
    facilitator.put(f"/todos/{todo['id']}/done", {"done": True})
    assert facilitator.get(f"/meetings/{mid}/summary").body == summary

    # An ended meeting accepts no more commands.
    for method, path, body in (
        ("POST", f"/meetings/{mid}/join", None),
        ("POST", f"/meetings/{mid}/end", None),
        ("PUT", f"/meetings/{mid}/rating", {"rating": 7}),
    ):
        assert facilitator.request(method, path, body).error == "meeting_ended", path
    assert (
        facilitator.post(f"/meetings/{mid}/advance", {"expected_section": "scorecard"}).error
        == "meeting_ended"
    )
    # ...and the team can start the next one.
    assert facilitator.post(START).status == 201


def test_seeded_meeting_summary_matches_the_contract(login):
    body = login("u5").get("/meetings/mt2/summary").body
    assert body == {
        "meeting_id": "mt2",
        "team_id": "team_lead",
        "facilitator_id": "u2",
        "started_at": "2026-11-04T15:00:00Z",
        "ended_at": "2026-11-04T16:20:00Z",
        "scorecard_week": "2026-10-26",
        "measurable_status": {
            "m1": "off_track",
            "m2": "on_track",
            "m3": "on_track",
            "m4": "off_track",
            "m5": "on_track",
        },
        "issues_solved": ["i6"],
        "todos_created": ["t30"],
        "attendee_ids": ["u1", "u2", "u3", "u4", "u5"],
        "rating": 8.3,
        "labels": {
            "users": {
                "u1": "Avery Admin",
                "u2": "Blake Brooks",
                "u3": "Casey Cho",
                "u4": "Dana Diaz",
                "u5": "Ellis Evans",
            },
            "measurables": {
                "m1": "New deals closed",
                "m2": "Customer churn",
                "m3": "Avg first response",
                "m4": "Payroll runs",
                "m5": "Cash on hand",
            },
            "issues": {"i6": "Payroll runs, week of Oct 26"},
            "todos": {"t30": "Set payroll reminder"},
        },
    }


def test_unknown_meetings(login):
    assert login("u1").get("/meetings/mt_nope").error == "not_found"
    assert login("u3").post("/meetings/mt_nope/join").error == "not_found"
