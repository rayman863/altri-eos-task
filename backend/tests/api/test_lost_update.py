"""Lost-update protection (bonus 1): If-Match on score edits and Issue priority."""

import asyncio

from tests.api.conftest import CSRF, asgi_request
from tests.db.conftest import query

SCORE = "/teams/team_lead/measurables/{mid}/scores/{week}"
OFF_TRACK = SCORE.format(mid="m1", week="2026-10-26")  # seeded "9", version 1
EMPTY = SCORE.format(mid="m1", week="2026-11-09")  # current week, no score yet


def cache_version(seeded) -> int:
    return query(seeded.owner_database_url, "SELECT cache_version FROM teams WHERE id='team_lead'")[
        0
    ][0]


def test_a_save_with_the_version_you_saw_goes_through_and_returns_the_new_one(login):
    u3 = login("u3")
    saved = u3.put(OFF_TRACK, {"value": "11"}, headers={"If-Match": '"1"'})
    assert saved.status == 200
    assert saved.body["value"] == "11" and saved.body["version"] > 1
    assert saved.headers["etag"] == f'"{saved.body["version"]}"'


def test_a_save_based_on_an_old_version_is_refused_with_the_current_value(login, seeded):
    u3, u2 = login("u3"), login("u2")
    assert u2.put(OFF_TRACK, {"value": "12"}).status == 200  # someone else, meanwhile
    before = cache_version(seeded)
    refused = u3.put(OFF_TRACK, {"value": "11"}, headers={"If-Match": '"1"'})
    assert (refused.status, refused.error) == (409, "stale_version")
    current = refused.body["error"]["details"]["current"]
    assert (current["week_start"], current["value"], current["status"]) == (
        "2026-10-26",
        "12",
        "on_track",
    )
    assert cache_version(seeded) == before  # rolled back: no write, no live event
    # With the version from the refusal, the next save goes through.
    retry = u3.put(OFF_TRACK, {"value": "11"}, headers={"If-Match": f'"{current["version"]}"'})
    assert (retry.status, retry.body["value"]) == (200, "11")


def test_without_if_match_the_last_save_wins_as_before(login):
    u3, u2 = login("u3"), login("u2")
    assert u2.put(OFF_TRACK, {"value": "12"}).status == 200
    assert u3.put(OFF_TRACK, {"value": "11"}).body["value"] == "11"


def test_an_empty_cell_is_version_0_and_a_filled_one_is_refused(login):
    u3, u2 = login("u3"), login("u2")
    assert u2.put(EMPTY, {"value": "7"}, headers={"If-Match": '"0"'}).status == 200
    refused = u3.put(EMPTY, {"value": "8"}, headers={"If-Match": '"0"'})
    assert refused.error == "stale_version"
    assert refused.body["error"]["details"]["current"]["value"] == "7"


def test_versions_never_repeat_after_a_clear_so_an_old_one_cannot_match_again(login):
    """A cleared score's row is deleted; the next save must not reuse version 1."""
    u3, u2 = login("u3"), login("u2")
    assert u2.delete(OFF_TRACK).status == 204
    again = u2.put(OFF_TRACK, {"value": "9"})
    assert again.body["version"] != 1
    refused = u3.put(OFF_TRACK, {"value": "11"}, headers={"If-Match": '"1"'})
    assert refused.error == "stale_version"


def test_clearing_takes_if_match_too(login):
    u3, u2 = login("u3"), login("u2")
    assert u2.put(OFF_TRACK, {"value": "12"}).status == 200
    assert u3.delete(OFF_TRACK, headers={"If-Match": '"1"'}).error == "stale_version"
    cells = u3.get("/teams/team_lead/scorecard").body["measurables"][0]["cells"]
    assert next(c for c in cells if c["week_start"] == "2026-10-26")["value"] == "12"


def test_star_and_weak_tags_and_lists(login):
    u3 = login("u3")
    assert u3.put(EMPTY, {"value": "1"}, headers={"If-Match": "*"}).error == "stale_version"
    assert u3.put(OFF_TRACK, {"value": "10"}, headers={"If-Match": "*"}).status == 200
    current = u3.get("/teams/team_lead/scorecard").body["measurables"][0]["cells"][10]
    tags = f'"999", W/"{current["version"]}"'
    assert u3.put(OFF_TRACK, {"value": "11"}, headers={"If-Match": tags}).status == 200


def test_a_malformed_if_match_is_a_validation_error(login):
    resp = login("u3").put(OFF_TRACK, {"value": "11"}, headers={"If-Match": '"abc"'})
    assert (resp.status, resp.error) == (422, "validation_failed")
    assert resp.body["error"]["details"]["fields"][0]["loc"] == ["header", "If-Match"]


def test_two_saves_from_the_same_version_at_once_one_wins_one_is_refused(app, login):
    """The check runs under the team lock, so both can't pass it."""
    tokens = [login("u3").token, login("u2").token]

    async def save(token: str, value: str):
        return await asgi_request(
            app,
            "PUT",
            f"/api/v1{OFF_TRACK}",
            json={"value": value},
            headers={**CSRF, "If-Match": '"1"'},
            cookie=token,
        )

    async def main():
        return await asyncio.gather(
            *(save(t, v) for t, v in zip(tokens, ("11", "12"), strict=True))
        )

    results = sorted(r.status for r in asyncio.run(main()))
    assert results == [200, 409]


def test_issue_priority_takes_if_match(login):
    u3, u4 = login("u3"), login("u4")
    seen = next(i for i in u3.get("/teams/team_lead/issues").body if i["id"] == "i4")
    assert u4.patch("/issues/i4", {"priority": 2}).status == 200  # someone else, meanwhile
    refused = u3.patch("/issues/i4", {"priority": 5}, headers={"If-Match": f'"{seen["version"]}"'})
    assert (refused.status, refused.error) == (409, "stale_version")
    assert refused.body["error"]["details"]["current"]["priority"] == 2
    current = refused.body["error"]["details"]["current"]["version"]
    ok = u3.patch("/issues/i4", {"priority": 5}, headers={"If-Match": f'"{current}"'})
    assert (ok.status, ok.body["priority"], ok.headers["etag"]) == (
        200,
        5,
        f'"{current + 1}"',
    )
