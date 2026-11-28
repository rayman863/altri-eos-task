"""Issues, To-Dos and Rocks (API contracts sections 6 to 8)."""

import pytest

# ---- issues ---------------------------------------------------------------------------------


def test_unsolved_issues_come_in_issue_order(login):
    body = login("u5").get("/teams/team_lead/issues").body
    assert [i["id"] for i in body] == ["i2", "i1", "i5", "i3", "i4"]
    assert all(i["solved_at"] is None for i in body)


def test_solved_issues_newest_first(login):
    body = login("u5").get("/teams/team_lead/issues?status=solved").body
    assert [i["id"] for i in body] == ["i6", "i7"]
    assert body[0]["resolution_note"]


def test_bad_status_filter(login):
    assert login("u5").get("/teams/team_lead/issues?status=open").error == "validation_failed"


def test_create_an_issue(login):
    resp = login("u4").post(
        "/teams/team_lead/issues", {"title": "  Trucks idle on Mondays  ", "priority": 3}
    )
    assert resp.status == 201
    issue = resp.body
    assert (issue["title"], issue["priority"], issue["source"]) == (
        "Trucks idle on Mondays",
        3,
        None,
    )
    assert issue["owner"] == {"id": "u4", "name": "Dana Diaz"}
    order = [i["id"] for i in login("u4").get("/teams/team_lead/issues").body]
    assert order.index(issue["id"]) == order.index("i3") + 1  # p3, newer than i3


@pytest.mark.parametrize(
    ("body", "loc"),
    [
        ({"title": "   "}, ["body", "title"]),
        ({"title": "x" * 201}, ["body", "title"]),
        ({"title": "ok", "priority": 9}, ["body", "priority"]),
        ({"title": "ok", "priority": "5"}, ["body", "priority"]),
        ({"title": "ok", "team_id": "team_sales"}, ["body", "team_id"]),
        ({}, ["body", "title"]),
    ],
)
def test_issue_validation(login, body, loc):
    resp = login("u4").post("/teams/team_lead/issues", body)
    assert (resp.status, resp.error) == (422, "validation_failed")
    assert resp.body["error"]["details"]["fields"][0]["loc"] == loc


def test_change_and_clear_priority(login):
    client = login("u3")
    resp = client.patch("/issues/i4", {"priority": 5})
    assert (resp.status, resp.body["priority"], resp.body["version"]) == (200, 5, 2)
    cleared = client.patch("/issues/i4", {"priority": None})
    assert (cleared.body["priority"], cleared.body["version"]) == (None, 3)
    assert client.patch("/issues/i4", {}).error == "validation_failed"  # priority is required


def test_solve_an_issue(login):
    client = login("u3")
    resp = client.post("/issues/i1/solve", {"resolution_note": "  Hired a recruiter.  "})
    assert resp.status == 200
    assert (resp.body["solved_at"], resp.body["resolution_note"]) == (
        "2026-11-11T15:00:00Z",
        "Hired a recruiter.",
    )
    again = client.post("/issues/i1/solve", {"resolution_note": "again"})
    assert (again.status, again.error) == (409, "already_solved")
    assert client.patch("/issues/i1", {"priority": 1}).error == "already_solved"
    assert client.post("/issues/i2/solve", {"resolution_note": "  "}).error == "validation_failed"


def test_todo_from_an_issue(login):
    client = login("u3")
    resp = client.post("/issues/i1/todos", {"title": "Call the recruiter", "owner_id": "u1"})
    assert resp.status == 201
    todo = resp.body
    assert todo["due_date"] == "2026-11-18"  # today + 7 days, company time
    assert todo["source_issue"] == {"id": "i1", "title": "Hiring pipeline is slow"}
    assert (todo["owner"]["id"], todo["done_at"], todo["overdue"]) == ("u1", None, False)
    issue = next(i for i in client.get("/teams/team_lead/issues").body if i["id"] == "i1")
    assert issue["todo_count"] == 1


@pytest.mark.parametrize("owner", ["u5", "u8", "u_nope"])  # Observer, other team, unknown
def test_todo_owner_must_be_eligible(login, owner):
    resp = login("u3").post("/issues/i1/todos", {"title": "X", "owner_id": owner})
    assert (resp.status, resp.error) == (422, "owner_not_eligible")


# ---- to-dos ---------------------------------------------------------------------------------


def test_todo_list(login):
    body = login("u5").get("/teams/team_lead/todos").body
    items = {t["id"]: t for t in body["items"]}
    assert sorted(i for i, t in items.items() if t["overdue"]) == ["t12", "t31"]
    assert items["t30"]["overdue"] is False and items["t30"]["due_date"] == "2026-11-11"
    assert items["t12"] == {
        "id": "t12",
        "title": "Publish hiring ad",
        "owner": {"id": "u3", "name": "Casey Cho"},
        "due_date": "2026-11-01",
        "done_at": None,
        "overdue": True,
        "source_issue": None,
        "created_at": "2026-10-25T21:00:00Z",
        "open_issue_id": None,
    }
    open_items = [t for t in body["items"] if t["done_at"] is None]
    done_items = [t for t in body["items"] if t["done_at"] is not None]
    assert body["items"] == open_items + done_items  # open first
    assert [t["due_date"] for t in open_items] == sorted(t["due_date"] for t in open_items)
    assert [t["done_at"] for t in done_items] == sorted(
        (t["done_at"] for t in done_items), reverse=True
    )
    assert body["last_closed_week_completion"] == {
        "week_start": "2026-11-02",
        "due": 10,
        "done": 9,
        "rate_percent": 90,
        "meets_target": True,
    }


def test_mark_done_is_idempotent(login, app):
    client = login("u3")
    done = client.put("/todos/t12/done", {"done": True})
    assert (done.status, done.body["done_at"], done.body["overdue"]) == (
        200,
        "2026-11-11T15:00:00Z",
        False,
    )
    from datetime import timedelta

    app.state.clock.advance(timedelta(hours=1))
    again = client.put("/todos/t12/done", {"done": True})
    assert again.body["done_at"] == "2026-11-11T15:00:00Z"  # keeps the original time
    undone = client.put("/todos/t12/done", {"done": False})
    assert (undone.body["done_at"], undone.body["overdue"]) == (None, True)
    assert client.put("/todos/t12/done", {"done": "yes"}).error == "validation_failed"
    assert client.put("/todos/t_nope/done", {"done": True}).error == "not_found"


# ---- rocks ----------------------------------------------------------------------------------


def test_rocks_with_computed_status(login):
    body = login("u5").get("/teams/team_lead/rocks").body
    assert body["quarter"] == "2026-Q4"
    rocks = {r["id"]: r for r in body["items"]}
    assert sorted(rocks) == ["r1", "r2", "r3", "r4", "r5"]
    r2 = rocks["r2"]
    assert (r2["seeded_status"], r2["status"], r2["progress_percent"]) == (
        "on_track",
        "off_track",
        13,
    )
    assert len(r2["milestones"]) == 8
    assert r2["milestones"][:2] == [
        {
            "id": "ms4",
            "title": "Job description approved",
            "due_date": "2026-10-10",
            "done": True,
            "past_due": False,
        },
        {
            "id": "ms5",
            "title": "Shortlist of 5",
            "due_date": "2026-11-10",
            "done": False,
            "past_due": True,
        },
    ]
    r1 = rocks["r1"]
    assert (r1["status"], r1["progress_percent"]) == ("on_track", 33)
    assert (
        next(ms for ms in r1["milestones"] if ms["id"] == "ms2")["past_due"] is False
    )  # due today
    assert {k: (rocks[k]["status"], rocks[k]["progress_percent"]) for k in ("r3", "r4", "r5")} == {
        "r3": ("complete", 100),
        "r4": ("off_track", 0),
        "r5": ("on_track", 0),
    }


def test_the_database_role_trigger_backs_up_the_api_check(login, monkeypatch):
    """If the API's own eligibility check ever misses (a race, or a bug), the role trigger
    refuses the row and the error mapper still answers 422 owner_not_eligible, not 500."""
    from app.services import issues

    async def always_eligible(session, user_id, team_id):
        return True

    monkeypatch.setattr(issues, "is_eligible_owner", always_eligible)
    resp = login("u3").post("/issues/i1/todos", {"title": "X", "owner_id": "u5"})  # Observer
    assert (resp.status, resp.error) == (422, "owner_not_eligible")
    assert resp.body["error"]["request_id"]
