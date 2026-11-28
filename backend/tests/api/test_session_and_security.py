"""Session cookie, CSRF, JSON-only writes, body limit, headers and error envelope
(plan 3.15, API contracts sections 1 and 3)."""

import time

import pytest

from app.config import Settings
from app.security import sign_session, verify_session
from tests.api.conftest import Client, session_token

SECRET = "x" * 40


# ---- session --------------------------------------------------------------------------------


def test_user_switcher_lists_the_seed(anon):
    resp = anon.get("/auth/users")
    assert resp.status == 200
    assert [u["id"] for u in resp.body] == [f"u{i}" for i in range(1, 10)]
    u2 = resp.body[1]
    assert u2 == {
        "id": "u2",
        "name": "Blake Brooks",
        "email": "blake@acme.test",
        "role": "team_member",
        "teams": [{"id": "team_lead", "name": "Leadership"}, {"id": "team_sales", "name": "Sales"}],
    }


def test_login_sets_a_hardened_cookie_and_returns_me(anon):
    resp = anon.post("/auth/login", {"user_id": "u3"})
    assert resp.status == 200
    cookie = resp.cookies[0]
    for attribute in ("HttpOnly", "SameSite=lax", "Path=/", "Max-Age=43200"):
        assert attribute.lower() in cookie.lower()
    assert "secure" not in cookie.lower()  # plain http://localhost
    assert resp.body == {
        "user": {
            "id": "u3",
            "name": "Casey Cho",
            "email": "casey@acme.test",
            "role": "team_member",
        },
        "teams": [{"id": "team_lead", "name": "Leadership", "can_write": True}],
        "company": {"id": "co_1", "name": "Acme Logistics", "timezone": "America/Chicago"},
        "clock": {
            "now": "2026-11-11T15:00:00Z",
            "today": "2026-11-11",
            "current_week": "2026-11-09",
            "last_closed_week": "2026-11-02",
        },
    }


def test_admin_sees_every_team_and_observers_cannot_write(login):
    assert [t["id"] for t in login("u1").get("/me").body["teams"]] == [
        "team_lead",
        "team_ops",
        "team_sales",
    ]
    assert login("u5").get("/me").body["teams"] == [
        {"id": "team_lead", "name": "Leadership", "can_write": False}
    ]


@pytest.mark.parametrize("user_id", ["u_nope", "u99"])
def test_unknown_users_cannot_log_in(anon, user_id):
    resp = anon.post("/auth/login", {"user_id": user_id})
    assert (resp.status, resp.error) == (401, "invalid_login")
    assert resp.cookies == []


def test_login_validates_the_id(anon):
    assert anon.post("/auth/login", {"user_id": "U1; DROP"}).error == "validation_failed"
    assert anon.post("/auth/login", {"user_id": "u1", "role": "admin"}).error == "validation_failed"


def test_tampered_and_expired_cookies_are_rejected(app):
    settings = app.state.settings
    good = sign_session(settings.session_secret, "u3")
    payload, signature = good.split(".")
    forged = sign_session("another-secret-that-is-long-enough-000", "u1")
    old = sign_session(settings.session_secret, "u3", issued_at=int(time.time()) - 13 * 3600)
    for token in (f"{payload}.{signature[:-2]}xx", forged, old, "garbage", f"{payload}."):
        resp = Client(app, token).get("/me")
        assert (resp.status, resp.error) == (401, "unauthenticated"), token
    assert Client(app, good).get("/me").status == 200


def test_session_tokens_round_trip_and_expire():
    token = sign_session(SECRET, "u2", issued_at=1_000_000)
    assert verify_session(SECRET, sign_session(SECRET, "u2", 3), 3600) == ("u2", 3)
    assert verify_session(SECRET, token, 3600, now=1_000_000 + 3599) == ("u2", 0)
    assert verify_session(SECRET, token, 3600, now=1_000_000 + 3601) is None
    assert verify_session("y" * 40, token, 3600, now=1_000_100) is None


def test_logout_clears_the_cookie(login):
    client = login("u3")
    resp = client.post("/auth/logout")
    assert resp.status == 204
    assert "max-age=0" in resp.cookies[0].lower()
    assert session_token(resp) is None


def test_logout_ends_the_session_even_if_the_cookie_was_kept(login, app):
    first = login("u3")
    second = login("u3")  # another browser, same user
    assert first.post("/auth/logout").status == 204
    # A copied cookie from before the logout no longer works, in any browser.
    assert first.get("/me").error == "unauthenticated"
    assert second.get("/me").error == "unauthenticated"
    # Signing in again works, with a token from the new epoch.
    again = login("u3")
    assert again.get("/me").status == 200
    # Other users are unaffected.
    assert login("u2").get("/me").status == 200


def test_tokens_from_an_old_epoch_are_refused(app, login):
    settings = app.state.settings
    login("u3").post("/auth/logout")  # u3 is now in epoch 1
    stale = sign_session(settings.session_secret, "u3", 0)
    current = sign_session(settings.session_secret, "u3", 1)
    assert Client(app, stale).get("/me").error == "unauthenticated"
    assert Client(app, current).get("/me").status == 200


def test_production_refuses_the_dev_secret():
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        Settings(app_env="production")
    assert Settings(app_env="production", session_secret="s" * 40).session_secret == "s" * 40


def test_a_settings_error_never_prints_the_secrets_it_was_given():
    """The error is logged at startup (app/preflight.py), so it names the problem only."""
    with pytest.raises(ValueError, match="SESSION_SECRET") as refused:
        Settings(
            app_env="production",
            session_secret="short-real-secret",
            database_url="postgresql+asyncpg://eos_app:db-password-123@db:5432/eos",
        )
    shown = str(refused.value)  # what a logged traceback shows
    assert "short-real-secret" not in shown
    assert "db-password-123" not in shown


# ---- request guards ---------------------------------------------------------------------------


def test_writes_need_the_csrf_header(login):
    client = login("u3")
    resp = client.put(
        "/teams/team_lead/measurables/m1/scores/2026-11-02",
        {"value": 9},
        headers={"x-eos-csrf": ""},
    )
    assert (resp.status, resp.error) == (403, "csrf_failed")


def test_writes_from_a_foreign_origin_are_refused(login):
    client = login("u3")
    path = "/teams/team_lead/measurables/m1/scores/2026-11-02"
    resp = client.put(path, {"value": 9}, headers={"origin": "http://localhost:9999"})
    assert (resp.status, resp.error) == (403, "csrf_failed")
    assert client.put(path, {"value": 9}, headers={"origin": "http://localhost:3000"}).status == 200


def test_writes_must_be_json(login):
    resp = login("u3").request(
        "POST",
        "/teams/team_lead/issues",
        body=b"title=x",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert (resp.status, resp.error) == (415, "unsupported_media_type")


def test_bodies_over_64_kb_are_refused(login):
    resp = login("u3").post("/teams/team_lead/issues", {"title": "x" * 70_000})
    assert (resp.status, resp.error) == (413, "payload_too_large")


def test_malformed_json_is_a_400(login):
    resp = login("u3").request("POST", "/teams/team_lead/issues", body=b'{"title": ')
    assert (resp.status, resp.error) == (400, "bad_request")


def test_bad_path_ids_never_reach_the_database(login):
    resp = login("u1").get("/teams/TEAM-LEAD'--/scorecard")
    assert resp.status == 422


def test_api_responses_carry_security_headers_and_request_ids(login):
    resp = login("u3").get("/teams/team_lead")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["cache-control"] == "no-store"
    error = login("u3").get("/teams/team_sales")
    assert error.body["error"]["request_id"] == error.headers["x-request-id"]
    assert error.headers["cache-control"] == "no-store"
