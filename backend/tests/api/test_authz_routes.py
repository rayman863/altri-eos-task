"""Route-table authorization test (plan 3.6).

Walks every operation in the app's OpenAPI schema, so an endpoint added later without an
access guard fails here:
- no session: every non-public route is 401;
- Observer (u5, Leadership): every write is 403, except signing out;
- Team Member of another team (u6, Sales): every Leadership-scoped route is 403, reads
  included, whether the team comes from the path or from a resource id (i1, t12).
"""

import re

import pytest

from app.main import create_app

PUBLIC = {
    ("GET", "/api/v1/auth/users"),
    ("POST", "/api/v1/auth/login"),
    ("GET", "/api/v1/ping"),
    ("GET", "/healthz"),
}
# Observers may sign out and join meetings (plan 3.7); every other write is refused.
OBSERVER_MAY_WRITE = {
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/meetings/{meeting_id}/join"),
}
# Meeting commands refuse Observers with their own 403 code (not the facilitator).
OBSERVER_REFUSALS = {"forbidden", "not_facilitator"}
SAMPLE = {
    "team_id": "team_lead",
    "measurable_id": "m1",
    "week_start": "2026-11-02",
    "issue_id": "i1",
    "todo_id": "t12",
    "meeting_id": "mt1",
    "rock_id": "r2",  # an off-track Rock of team_lead (bonus 3)
}
TEAM_SCOPED = re.compile(r"\{(team_id|issue_id|todo_id|meeting_id)\}")


def operations() -> list[tuple[str, str]]:
    schema = create_app().openapi()
    return sorted(
        (method.upper(), path)
        for path, item in schema["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    )


OPERATIONS = operations()


def concrete(path: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: SAMPLE[m.group(1)], path).removeprefix("/api/v1")


def test_the_route_table_is_not_empty():
    # Guards against this file passing vacuously if route discovery ever breaks.
    assert len(OPERATIONS) >= 18
    assert (
        "POST",
        "/api/v1/teams/{team_id}/measurables/{measurable_id}/scores/{week_start}/issue",
    ) in OPERATIONS


@pytest.mark.parametrize(("method", "path"), [op for op in OPERATIONS if op not in PUBLIC])
def test_every_private_route_needs_a_session(anon, method, path):
    resp = anon.request(method, concrete(path))
    assert resp.status == 401, (method, path, resp.body)
    assert resp.error == "unauthenticated"


@pytest.mark.parametrize(
    ("method", "path"),
    [op for op in OPERATIONS if op[0] != "GET" and op not in PUBLIC | OBSERVER_MAY_WRITE],
)
def test_observers_cannot_write(login, method, path):
    resp = login("u5").request(method, concrete(path))
    assert resp.status == 403, (method, path, resp.body)
    assert resp.error in OBSERVER_REFUSALS


@pytest.mark.parametrize(("method", "path"), [op for op in OPERATIONS if TEAM_SCOPED.search(op[1])])
def test_other_teams_members_are_refused(login, method, path):
    resp = login("u6").request(method, concrete(path))  # u6 is only in Sales
    assert resp.status == 403, (method, path, resp.body)
    assert resp.error == "forbidden"


@pytest.mark.parametrize(
    ("method", "path"), [op for op in OPERATIONS if TEAM_SCOPED.search(op[1]) and op[0] == "GET"]
)
def test_observers_can_read_their_team(login, method, path):
    resp = login("u5").request(method, concrete(path))
    assert resp.status == 200, (method, path, resp.body)


def test_admin_reaches_every_team_and_gets_404_for_unknown_ones(login):
    admin = login("u1")
    for team in ("team_lead", "team_sales", "team_ops"):
        assert admin.get(f"/teams/{team}").status == 200
    assert admin.get("/teams/team_nope").error == "not_found"


def test_members_get_403_not_404_for_unknown_teams(login):
    # An inaccessible team is 403 even for a guessed id (no existence oracle).
    resp = login("u3").get("/teams/team_nope")
    assert (resp.status, resp.error) == (403, "forbidden")


def test_resource_ids_resolve_to_their_team_first(login):
    sales = login("u6")
    # i8 is a Sales Issue: u6 may change it, but not Leadership's i1.
    assert sales.patch("/issues/i8", {"priority": 4}).status == 200
    assert sales.patch("/issues/i1", {"priority": 4}).status == 403
    assert sales.patch("/issues/i_nope", {"priority": 4}).status == 404
