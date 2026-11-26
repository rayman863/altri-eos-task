"""Make it an Issue: dedupe, the off-track rule, and exactly one Issue under concurrent
clicks (brief 2.6, plan 3.8, API contracts section 5)."""

import asyncio

from tests.api.conftest import CSRF, asgi_request
from tests.db.conftest import query

MAKE = "/teams/team_lead/measurables/{mid}/scores/{week}/issue"


def test_existing_open_issue_is_returned(login):
    resp = login("u3").post(MAKE.format(mid="m1", week="2026-11-02"))
    assert resp.status == 200
    assert resp.body == {
        "created": False,
        "issue": {
            "id": "i5",
            "title": "New deals closed, week of Nov 2",
            "owner": {"id": "u2", "name": "Blake Brooks"},
            "priority": 4,
            "created_at": "2026-11-09T16:00:00Z",
            "solved_at": None,
            "resolution_note": None,
            "source": {
                "kind": "measurable_week",
                "measurable_id": "m1",
                "measurable_name": "New deals closed",
                "week_start": "2026-11-02",
            },
            "todo_count": 0,
            "version": 1,
        },
    }


def test_off_track_cell_creates_one_issue(login):
    client = login("u3")
    first = client.post(MAKE.format(mid="m1", week="2026-10-26"))
    assert first.status == 201
    issue = first.body["issue"]
    assert first.body["created"] is True
    assert issue["id"].startswith("i_")
    assert issue["title"] == "New deals closed, week of Oct 26"
    assert issue["owner"] == {"id": "u3", "name": "Casey Cho"}
    assert (issue["priority"], issue["created_at"]) == (None, "2026-11-11T15:00:00Z")
    again = client.post(MAKE.format(mid="m1", week="2026-10-26"))
    assert (again.status, again.body["created"], again.body["issue"]["id"]) == (
        200,
        False,
        issue["id"],
    )
    cell = next(
        r for r in client.get("/teams/team_lead/scorecard").body["measurables"] if r["id"] == "m1"
    )
    assert (
        next(c for c in cell["cells"] if c["week_start"] == "2026-10-26")["open_issue_id"]
        == issue["id"]
    )


def test_on_track_cell_is_refused(login):
    resp = login("u3").post(MAKE.format(mid="m1", week="2026-09-07"))  # 10, goal >= 10
    assert (resp.status, resp.error) == (422, "cell_not_off_track")


def test_pending_current_week_is_refused(login):
    resp = login("u3").post(MAKE.format(mid="m1", week="2026-11-09"))
    assert (resp.status, resp.error) == (422, "cell_not_off_track")


def test_a_new_issue_is_allowed_after_the_old_one_was_solved(login):
    resp = login("u3").post(MAKE.format(mid="m4", week="2026-10-26"))  # only the solved i6
    assert resp.status == 201


def test_twenty_concurrent_clicks_make_exactly_one_issue(app, login, seeded):
    token = login("u3").token

    async def click() -> tuple[int, str]:
        resp = await asgi_request(
            app,
            "POST",
            "/api/v1" + MAKE.format(mid="m1", week="2026-10-26"),
            json={},
            headers=CSRF,
            cookie=token,
        )
        return resp.status, resp.body["issue"]["id"]

    async def burst() -> list[tuple[int, str]]:
        return await asyncio.gather(*(click() for _ in range(20)))

    results = asyncio.run(burst())
    statuses = sorted(status for status, _ in results)
    assert statuses == [200] * 19 + [201]
    assert len({issue_id for _, issue_id in results}) == 1
    count = query(
        seeded.owner_database_url,
        "SELECT count(*) FROM issues WHERE source_measurable_id = 'm1'"
        " AND source_week_start = '2026-10-26'",
    )[0][0]
    assert count == 1


def test_an_open_issue_is_returned_even_after_its_week_left_the_scorecard(login, seeded):
    query(
        seeded.owner_database_url,
        "INSERT INTO issues (id, team_id, owner_id, title, created_at, source_kind,"
        " source_measurable_id, source_week_start) VALUES ('i_old', 'team_lead', 'u2',"
        " 'New deals closed, week of Aug 10', '2026-08-17T15:00:00Z', 'measurable_week',"
        " 'm1', '2026-08-10')",
    )
    resp = login("u3").post(MAKE.format(mid="m1", week="2026-08-10"))  # before the 13 weeks
    assert (resp.status, resp.body["created"], resp.body["issue"]["id"]) == (200, False, "i_old")
    fresh = login("u3").post(MAKE.format(mid="m1", week="2026-08-03"))  # no Issue: refused
    assert (fresh.status, fresh.error) == (422, "week_out_of_range")


def _race(monkeypatch, *, winner_visible: bool) -> None:
    """Make step 1 miss an Issue that another transaction committed (a write path without
    the team lock), so the insert hits the partial unique index."""
    from app.services import scorecard

    real = scorecard._open_issue_id
    calls = {"n": 0}

    async def racing(session, measurable_id, week):
        calls["n"] += 1
        if calls["n"] == 1 or not winner_visible:
            return None
        return await real(session, measurable_id, week)

    monkeypatch.setattr(scorecard, "_open_issue_id", racing)


def test_insert_conflict_returns_the_winner(login, monkeypatch):
    _race(monkeypatch, winner_visible=True)
    resp = login("u3").post(MAKE.format(mid="m1", week="2026-11-02"))  # i5 is open
    assert (resp.status, resp.body["created"], resp.body["issue"]["id"]) == (200, False, "i5")


def test_insert_conflict_without_a_visible_winner_asks_to_retry(login, monkeypatch, seeded):
    _race(monkeypatch, winner_visible=False)
    resp = login("u3").post(MAKE.format(mid="m1", week="2026-11-02"))
    assert (resp.status, resp.error) == (409, "conflict")
    count = query(
        seeded.owner_database_url,
        "SELECT count(*) FROM issues WHERE source_measurable_id = 'm1'"
        " AND source_week_start = '2026-11-02'",
    )[0][0]
    assert count == 1  # still only i5
