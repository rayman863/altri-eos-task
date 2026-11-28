"""Teams and the Scorecard: contract examples, score edits and validation
(API contracts sections 4 and 5)."""

import pytest

from tests.db.conftest import query

SCORE = "/teams/team_lead/measurables/{mid}/scores/{week}"


def cells(scorecard: dict, mid: str) -> dict[str, dict]:
    row = next(r for r in scorecard["measurables"] if r["id"] == mid)
    return {c["week_start"]: c for c in row["cells"]}


def cache_version(settings, team: str = "team_lead") -> int:
    return query(
        settings.owner_database_url, f"SELECT cache_version FROM teams WHERE id = '{team}'"
    )[0][0]  # noqa: S608


# ---- teams ----------------------------------------------------------------------------------


def test_team_list_is_what_the_user_can_see(login):
    assert login("u2").get("/teams").body == [
        {"id": "team_lead", "name": "Leadership", "active_meeting_id": None},
        {"id": "team_sales", "name": "Sales", "active_meeting_id": None},
    ]
    assert [t["id"] for t in login("u1").get("/teams").body] == [
        "team_lead",
        "team_ops",
        "team_sales",
    ]


def test_team_detail_members_and_eligible_owners(login):
    body = login("u5").get("/teams/team_lead").body
    assert [(m["id"], m["role"]) for m in body["members"]] == [
        ("u1", "admin"),
        ("u2", "team_member"),
        ("u3", "team_member"),
        ("u4", "team_member"),
        ("u5", "observer"),
    ]
    assert [o["id"] for o in body["eligible_owners"]] == ["u1", "u2", "u3", "u4"]
    assert body["active_meeting"] is None
    sales = login("u1").get("/teams/team_sales").body
    assert [o["id"] for o in sales["eligible_owners"]] == ["u1", "u2", "u6"]


# ---- scorecard ------------------------------------------------------------------------------


def test_scorecard_contract_example(login):
    body = login("u3").get("/teams/team_lead/scorecard").body
    assert len(body["weeks"]) == 13
    assert (body["weeks"][0], body["weeks"][-1]) == ("2026-08-17", "2026-11-09")
    assert (body["current_week"], body["last_closed_week"]) == ("2026-11-09", "2026-11-02")
    m1 = next(r for r in body["measurables"] if r["id"] == "m1")
    assert {k: m1[k] for k in ("name", "unit", "owner", "goal")} == {
        "name": "New deals closed",
        "unit": "count",
        "owner": {"id": "u2", "name": "Blake Brooks"},
        "goal": {"type": "at_least", "value": "10"},
    }
    c = cells(body, "m1")
    assert len(c) == 13
    assert c["2026-10-26"] == {
        "week_start": "2026-10-26",
        "value": "9",
        "status": "off_track",
        "version": 1,
        "open_issue_id": None,
    }
    assert c["2026-11-02"] == {
        "week_start": "2026-11-02",
        "value": "8",
        "status": "off_track",
        "version": 1,
        "open_issue_id": "i5",
    }
    assert c["2026-11-09"] == {
        "week_start": "2026-11-09",
        "value": None,
        "status": "pending",
        "version": None,
        "open_issue_id": None,
    }


def test_goals_and_decimals_are_exact_strings(login):
    body = login("u3").get("/teams/team_lead/scorecard").body
    goals = {r["id"]: r["goal"] for r in body["measurables"]}
    assert goals["m2"] == {"type": "at_most", "value": "3"}
    assert goals["m3"] == {"type": "between", "min": "2", "max": "4"}
    assert goals["m4"] == {"type": "exactly", "value": "1"}
    m3 = cells(body, "m3")
    assert {w: m3[w]["value"] for w in ("2026-09-07", "2026-10-12")} == {
        "2026-09-07": "4.5",
        "2026-10-12": "4.1",
    }
    # m5 has gaps in closed weeks: missing cells are off track, not absent.
    m5 = cells(body, "m5")
    assert (m5["2026-10-19"]["value"], m5["2026-10-19"]["status"]) == (None, "off_track")
    assert (m5["2026-11-09"]["value"], m5["2026-11-09"]["status"]) == ("520", "on_track")


def test_setting_a_score_recomputes_the_cell_and_bumps_the_version(login, seeded):
    before = cache_version(seeded)
    client = login("u3")
    resp = client.put(SCORE.format(mid="m1", week="2026-10-26"), {"value": "11"})
    assert resp.status == 200
    assert resp.body == {
        "week_start": "2026-10-26",
        "value": "11",
        "status": "on_track",
        "version": 2,
        "open_issue_id": None,
    }
    new = client.put(SCORE.format(mid="m1", week="2026-11-09"), {"value": 4.5})
    assert (
        new.body["value"] == "4.5"
        and new.body["version"] > resp.body["version"]  # versions never repeat (migration 0005)
        and new.body["status"] == "off_track"
    )
    assert cache_version(seeded) == before + 2  # every team write bumps it first


def test_clearing_a_score(login):
    client = login("u3")
    assert client.delete(SCORE.format(mid="m1", week="2026-10-26")).status == 204
    cell = cells(client.get("/teams/team_lead/scorecard").body, "m1")["2026-10-26"]
    assert (cell["value"], cell["status"], cell["version"]) == (None, "off_track", None)


@pytest.mark.parametrize(
    "value",
    ["abc", "1.23456", 2_000_000_000, "NaN", "Infinity", True, None, "", [], {"v": 1}],
)
def test_bad_score_values_are_rejected(login, value):
    resp = login("u3").put(SCORE.format(mid="m1", week="2026-10-26"), {"value": value})
    assert (resp.status, resp.error) == (422, "validation_failed"), value


def test_unknown_fields_are_rejected(login):
    resp = login("u3").put(SCORE.format(mid="m1", week="2026-10-26"), {"value": 1, "version": 99})
    assert resp.error == "validation_failed"
    assert resp.body["error"]["details"]["fields"][0]["loc"] == ["body", "version"]


@pytest.mark.parametrize(
    "week",
    [
        "2026-11-03",  # a Tuesday
        "2026-08-10",  # a Monday before the 13 shown weeks
        "2026-11-16",  # next week: not shown yet
    ],
)
def test_weeks_must_be_shown_mondays(login, week):
    resp = login("u3").put(SCORE.format(mid="m1", week=week), {"value": 1})
    assert (resp.status, resp.error) == (422, "week_out_of_range")


def test_measurables_of_another_team_are_not_found(login):
    resp = login("u1").put(SCORE.format(mid="m6", week="2026-11-02"), {"value": 1})  # m6 is Sales
    assert (resp.status, resp.error) == (404, "not_found")


def test_failed_writes_roll_back_the_cache_bump(login, seeded):
    before = cache_version(seeded)
    login("u3").put(SCORE.format(mid="m1", week="2026-11-03"), {"value": 1})
    assert cache_version(seeded) == before
