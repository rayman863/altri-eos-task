"""Two real API processes (layer L1, plan 3.13 and section 6).

`docker compose up` runs Uvicorn with `--workers 2`, and the kernel decides which worker
takes which connection, so a stack test can't promise that the facilitator and a follower
land on different workers. These tests make it certain: they start the shipping entry
point (`uvicorn app.main:app`) twice, as two OS processes on two ports, on eos_test with
the ticking clock, and drive them over real HTTP and SSE:

- both processes start at the same moment and still anchor one business clock;
- a follower streaming from process B follows the meeting the facilitator runs on A;
- SIGTERM ends B's open stream at once, B exits, and A carries on;
- the preflight the image runs before Uvicorn (app/preflight.py) passes on a good setup
  and stops a bad one at once, since Uvicorn's parent would restart failing workers forever.

The in-process versions in test_live.py cover the same paths faster; these prove them
across a real process boundary, with each process's own signal handling.
"""

import contextlib
import http.client
import json
import os
import queue
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from email.message import Message
from typing import Any

import pytest

from tests.db.conftest import query

EVENTS = "/api/v1/teams/team_lead/events"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ApiProcess:
    """One `uvicorn app.main:app` process; its JSON log lines are collected as they come."""

    def __init__(self, env: dict[str, str]) -> None:
        self.port = free_port()
        self.logs: list[dict[str, Any]] = []
        self.proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--no-access-log",
                "--timeout-graceful-shutdown",
                "20",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        threading.Thread(target=self._collect_logs, daemon=True).start()

    def _collect_logs(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            try:
                self.logs.append(json.loads(line))
            except ValueError:  # Uvicorn's own plain lines before logging is set up
                self.logs.append({"msg": line.rstrip()})

    def log_entry(self, msg: str, timeout: float = 2.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for entry in list(self.logs):
                if entry.get("msg") == msg:
                    return entry
            time.sleep(0.05)
        raise AssertionError(f"no {msg!r} log line in {self.logs[-10:]}")

    def request(
        self, method: str, path: str, body: Any = None, cookie: str | None = None
    ) -> tuple[int, Message, Any]:
        headers: dict[str, str] = {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers |= {"content-type": "application/json", "x-eos-csrf": "1"}
        if cookie:
            headers["cookie"] = f"eos_session={cookie}"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, resp.headers, json.loads(raw) if raw else None
        finally:
            conn.close()

    def login(self, user_id: str) -> str:
        status, headers, _ = self.request("POST", "/api/v1/auth/login", {"user_id": user_id})
        assert status == 200
        for value in headers.get_all("set-cookie") or []:
            name, _, rest = value.partition("=")
            if name == "eos_session":
                return rest.split(";", 1)[0].strip('"')
        raise AssertionError("login set no session cookie")

    def wait_healthy(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(f"API process exited early: {self.logs[-10:]}")
            try:
                status, _, body = self.request("GET", "/healthz")
                if status == 200 and body["realtime"]["listener"] == "ok":
                    return
            except OSError:
                pass  # not listening yet
            time.sleep(0.1)
        raise AssertionError(f"API process never became healthy: {self.logs[-10:]}")

    def stop(self) -> int:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
        try:
            return self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            raise


class EventStream:
    """An SSE stream read on its own thread, like a browser's EventSource (no reconnect)."""

    def __init__(self, api: ApiProcess, cookie: str) -> None:
        self.events: queue.Queue[tuple[str, dict[str, Any], float]] = queue.Queue()
        self.ended = threading.Event()
        self.conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=30)
        self.conn.request("GET", EVENTS, headers={"cookie": f"eos_session={cookie}"})
        self.sock = self.conn.sock  # kept: the connection may hand it to the response
        self.resp = self.conn.getresponse()
        assert self.resp.status == 200
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        fields: dict[str, str] = {}
        try:
            for raw in self.resp:  # one line at a time, chunked encoding undone
                line = raw.decode().rstrip("\n")
                if not line:
                    if "event" in fields:
                        event = (fields["event"], json.loads(fields["data"]), time.monotonic())
                        self.events.put(event)
                    fields = {}
                elif not line.startswith(":"):  # ": ping" heartbeats are comments
                    key, _, value = line.partition(": ")
                    fields[key] = value
        except (OSError, http.client.HTTPException):
            pass
        finally:
            self.ended.set()

    def next(self, name: str, timeout: float = 3.0) -> tuple[dict[str, Any], float]:
        """The next `name` event and when it arrived (other events are skipped)."""
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                event, data, arrived = self.events.get(timeout=remaining)
            except queue.Empty:
                break
            if event == name:
                return data, arrived
        raise AssertionError(f"no {name} event within {timeout} s")

    def close(self) -> None:
        """Hang up like a closed tab: the reader sees EOF and ends before the close."""
        with contextlib.suppress(OSError):
            self.sock.shutdown(socket.SHUT_RDWR)
        self.ended.wait(timeout=2)
        self.conn.close()


def api_env(seeded) -> dict[str, str]:
    return {
        **os.environ,
        "DATABASE_URL": seeded.database_url,
        "OWNER_DATABASE_URL": seeded.owner_database_url,
        "READONLY_DATABASE_URL": seeded.readonly_database_url,
        "APP_NOW": seeded.app_now,
        # The real clock of `docker compose up`, anchored in the database (plan 3.2).
        "APP_CLOCK_MODE": "ticking",
        "LOG_PAYLOADS": "false",
    }


def preflight(env: dict[str, str]) -> tuple[int, str]:
    """`python -m app.preflight`, as the API image runs it before Uvicorn."""
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", "app.preflight"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return done.returncode, done.stdout + done.stderr


@pytest.fixture
def two_apis(seeded) -> Iterator[tuple[ApiProcess, ApiProcess]]:
    env = api_env(seeded)
    # Started together on purpose: both race to create the clock anchor (the seed reset
    # removed it), the way the workers of a fresh `--workers 2` start do.
    apis = (ApiProcess(env), ApiProcess(env))
    try:
        for api in apis:
            api.wait_healthy()
        yield apis
    finally:
        # Every process is stopped even if one of them hangs; then the hang is reported.
        with contextlib.ExitStack() as stops:
            for api in apis:
                stops.callback(api.stop)


def test_two_processes_started_together_share_one_business_clock(two_apis, seeded):
    a, b = two_apis
    anchored = [api.log_entry("business clock anchored") for api in (a, b)]
    assert anchored[0]["anchored_at"] == anchored[1]["anchored_at"]
    assert query(seeded.owner_database_url, "SELECT count(*) FROM clock_anchor")[0][0] == 1


def test_a_follower_on_one_process_follows_a_meeting_run_on_the_other(two_apis):
    a, b = two_apis
    facilitator, follower = a.login("u3"), b.login("u5")
    stream = EventStream(b, follower)
    try:
        snapshot, _ = stream.next("snapshot")
        assert snapshot["active_meeting"] is None

        status, _, meeting = a.request(
            "POST", "/api/v1/teams/team_lead/meetings", {}, cookie=facilitator
        )
        assert status == 201
        state, _ = stream.next("meeting.state")
        assert (state["id"], state["section"]) == (meeting["id"], "scorecard")

        status, _, _ = a.request(
            "POST",
            f"/api/v1/meetings/{meeting['id']}/advance",
            {"expected_section": "scorecard"},
            cookie=facilitator,
        )
        committed = time.monotonic()
        assert status == 200
        state, arrived = stream.next("meeting.state")
        assert state["section"] == "ids"
        assert arrived - committed < 1.0  # the ~1 s sync target, across processes
    finally:
        stream.close()


def test_sigterm_ends_open_streams_at_once_and_the_other_process_carries_on(two_apis):
    a, b = two_apis
    stream = EventStream(b, b.login("u5"))
    try:
        stream.next("snapshot")
        sent = time.monotonic()
        b.proc.send_signal(signal.SIGTERM)
        assert stream.ended.wait(timeout=5), "the stream outlived SIGTERM"
        ended_after = time.monotonic() - sent
        exit_code = b.proc.wait(timeout=10)
    finally:
        stream.close()
    # Not Uvicorn's 20 s graceful-shutdown limit: the shutdown hook ends streams at once.
    assert ended_after < 3.0
    # Uvicorn re-raises the signal after a clean shutdown, so the exit is "killed by
    # SIGTERM" (143 in Docker), or 0.
    assert exit_code in (0, -signal.SIGTERM)
    assert b.log_entry("api stopped")
    # A browser's EventSource reconnects, and the other process is still serving.
    status, _, health = a.request("GET", "/healthz")
    assert (status, health["status"]) == (200, "ok")
    assert health["worker"] == a.proc.pid


def test_preflight_runs_one_worker_startup_and_passes(seeded):
    """The API image runs this before `uvicorn --workers N` (backend/Dockerfile)."""
    code, output = preflight(api_env(seeded))
    assert code == 0, output
    assert "api preflight passed" in output
    assert '"api started"' not in output  # the startup it ran stays quiet; workers log theirs
    # It ran the real startup, so the business clock is anchored before any worker starts.
    assert query(seeded.owner_database_url, "SELECT count(*) FROM clock_anchor")[0][0] == 1


def test_preflight_fails_fast_where_every_worker_would_fail(seeded):
    """Uvicorn's parent would restart such workers forever; the preflight stops the start."""
    env = api_env(seeded) | {"APP_ENV": "production"}  # with the dev-only session secret
    started = time.monotonic()
    code, output = preflight(env)
    assert code == 1
    assert "api preflight failed" in output
    assert "SESSION_SECRET must be a real secret" in output
    assert time.monotonic() - started < 30
