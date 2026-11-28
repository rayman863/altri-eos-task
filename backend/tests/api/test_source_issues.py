"""Make it an Issue from an off-track Rock or an overdue To-Do (bonus 3).

The same rules as for a Scorecard cell (test_make_issue.py): one open Issue per source,
even under simultaneous clicks; only a source that qualifies right now; the clicker owns it.
At the seed's now (2026-11-11) team_lead has off-track Rocks r2 and r4 (r1, r5 on track, r3
complete) and overdue To-Dos t12 and t31.
"""

import asyncio

import pytest

from tests.api.conftest import CSRF, asgi_request
from tests.db.conftest import query

ROCK = "/teams/team_lead/rocks/{rock}/issue"
TODO = "/todos/{todo}/issue"


def open_issues(seeded, column: str, source: str) -> int:
    return query(
        seeded.owner_database_url,
        f"SELECT count(*) FROM issues WHERE {column} = :s AND solved_at IS NULL",
        s=source,
    )[0][0]


def test_an_off_track_rock_becomes_one_issue(login, seeded):
    u3 = login("u3")
    made = u3.post(ROCK.format(rock="r2"))
    assert (made.status, made.body["created"]) == (201, True)
    issue = made.body["issue"]
    assert issue["title"] == "Rock off track: Hire VP of Sales"
    assert issue["source"] == {"kind": "rock", "rock_id": "r2", "rock_title": "Hire VP of Sales"}
    assert issue["owner"]["id"] == "u3"  # the clicker owns it
    again = login("u4").post(ROCK.format(rock="r2"))
    assert (again.status, again.body["created"], again.body["issue"]["id"]) == (
        200,
        False,
        issue["id"],
    )
    assert open_issues(seeded, "source_rock_id", "r2") == 1


def test_the_rock_list_links_its_open_issue_right_after_the_click(login):
    """Rocks are cached per team version: a new Issue must show at once."""
    u3 = login("u3")
    before = {r["id"]: r for r in u3.get("/teams/team_lead/rocks").body["items"]}
    assert before["r2"]["open_issue_id"] is None
    issue_id = u3.post(ROCK.format(rock="r2")).body["issue"]["id"]
    after = {r["id"]: r for r in u3.get("/teams/team_lead/rocks").body["items"]}
    assert after["r2"]["open_issue_id"] == issue_id
    assert after["r4"]["open_issue_id"] is None


@pytest.mark.parametrize("rock", ["r1", "r3"])
def test_a_rock_that_is_not_off_track_is_refused(login, rock):
    resp = login("u3").post(ROCK.format(rock=rock))
    assert (resp.status, resp.error) == (422, "rock_not_off_track")


def test_a_rock_of_another_team_is_not_found_here_and_forbidden_there(login):
    u3 = login("u3")
    assert u3.post(ROCK.format(rock="r6")).error == "not_found"  # team_sales's Rock
    assert u3.post("/teams/team_sales/rocks/r6/issue").error == "forbidden"


def test_an_observer_cannot(login):
    assert login("u5").post(ROCK.format(rock="r2")).error == "forbidden"
    assert login("u5").post(TODO.format(todo="t12")).error == "forbidden"


def test_an_overdue_todo_becomes_one_issue(login, seeded):
    u3 = login("u3")
    made = u3.post(TODO.format(todo="t12"))
    assert (made.status, made.body["created"]) == (201, True)
    issue = made.body["issue"]
    assert issue["title"] == "Overdue To-Do: Publish hiring ad"
    assert issue["source"] == {"kind": "todo", "todo_id": "t12", "todo_title": "Publish hiring ad"}
    again = u3.post(TODO.format(todo="t12"))
    assert (again.status, again.body["issue"]["id"]) == (200, issue["id"])
    todos = {t["id"]: t for t in u3.get("/teams/team_lead/todos").body["items"]}
    assert todos["t12"]["open_issue_id"] == issue["id"]
    assert open_issues(seeded, "source_todo_id", "t12") == 1


def test_a_todo_that_is_not_overdue_is_refused(login):
    u3 = login("u3")
    items = u3.get("/teams/team_lead/todos").body["items"]
    on_time = next(t for t in items if not t["overdue"] and t["done_at"] is None)
    done = next(t for t in items if t["done_at"] is not None)
    for todo in (on_time, done):
        resp = u3.post(TODO.format(todo=todo["id"]))
        assert (resp.status, resp.error) == (422, "todo_not_overdue"), todo["id"]


def test_a_todo_of_another_team_is_forbidden(login, seeded):
    sales_todo = query(
        seeded.owner_database_url, "SELECT id FROM todos WHERE team_id = 'team_sales' LIMIT 1"
    )[0][0]
    assert login("u3").post(TODO.format(todo=sales_todo)).error == "forbidden"


@pytest.mark.parametrize(
    ("path", "column", "source"),
    [
        (ROCK.format(rock="r4"), "source_rock_id", "r4"),
        (TODO.format(todo="t31"), "source_todo_id", "t31"),
    ],
)
def test_twenty_concurrent_clicks_make_exactly_one_issue(app, login, seeded, path, column, source):
    tokens = [login(u).token for u in ("u2", "u3", "u4")]

    async def click(i: int):
        return await asyncio_request(app, path, tokens[i % len(tokens)])

    async def main():
        return await asyncio.gather(*(click(i) for i in range(20)))

    results = asyncio.run(main())
    statuses = sorted(r.status for r in results)
    assert statuses == [200] * 19 + [201]
    assert len({r.body["issue"]["id"] for r in results}) == 1
    assert open_issues(seeded, column, source) == 1


async def asyncio_request(app, path: str, token: str):
    return await asgi_request(app, "POST", f"/api/v1{path}", json={}, headers=CSRF, cookie=token)


def test_once_solved_a_new_issue_can_be_made_for_the_same_source(login):
    u3 = login("u3")
    first = u3.post(ROCK.format(rock="r2")).body["issue"]["id"]
    assert u3.post(f"/issues/{first}/solve", {"resolution_note": "Two finalists"}).status == 200
    second = u3.post(ROCK.format(rock="r2"))
    assert second.status == 201 and second.body["issue"]["id"] != first
