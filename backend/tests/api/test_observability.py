"""Observability extras (layer L5): gzip, worker tags in the logs, the pool leak watch and
the connection budget (plan 3.10, 3.12, 3.16)."""

import asyncio
import gzip
import json
import logging
import os
import subprocess
import sys

import pytest
from sqlalchemy import text

from app.db import LeakWatch, connection_budget, make_engine
from app.logging import JsonFormatter, request_id_var
from app.main import create_app
from tests.api.conftest import asgi_request, wire_for_tests

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get(app, path: str, cookie: str | None = None, **headers: str):
    return asyncio.run(
        asgi_request(app, "GET", path, headers=headers, cookie=cookie, disconnect_after=0.5)
    )


# ---- gzip ------------------------------------------------------------------------------------


def test_large_responses_are_gzipped_for_clients_that_ask(app, login):
    token = login("u3").token
    plain = get(app, "/api/v1/teams/team_lead/scorecard", token)
    zipped = get(app, "/api/v1/teams/team_lead/scorecard", token, **{"accept-encoding": "gzip"})
    assert "content-encoding" not in plain.headers  # no Accept-Encoding, no gzip
    assert zipped.headers["content-encoding"] == "gzip"
    assert gzip.decompress(zipped.raw) == plain.raw
    assert len(zipped.raw) < len(plain.raw) / 3


def test_small_responses_and_live_streams_are_never_gzipped(app, login):
    small = get(app, "/api/v1/ping", **{"accept-encoding": "gzip"})
    assert "content-encoding" not in small.headers  # under 1 KB
    stream = get(
        app, "/api/v1/teams/team_lead/events", login("u3").token, **{"accept-encoding": "gzip"}
    )
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "content-encoding" not in stream.headers  # events must never wait in a buffer
    assert b"event: snapshot" in stream.raw


def test_gzip_switched_off(seeded):
    app = create_app(seeded.model_copy(update={"gzip_enabled": False}))
    engine = wire_for_tests(app, seeded)
    try:
        resp = get(app, "/openapi.json", **{"accept-encoding": "gzip"})
        assert resp.status == 200 and "content-encoding" not in resp.headers
    finally:
        asyncio.run(engine.dispose())


# ---- worker tags -----------------------------------------------------------------------------


def format_line(formatter: JsonFormatter, **extra: object) -> dict:
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, "hello", None, None)
    record.__dict__.update(extra)
    return json.loads(formatter.format(record))


def test_log_lines_carry_the_worker_and_drop_uvicorns_coloured_copy():
    line = format_line(JsonFormatter(worker_tags=True), color_message="\x1b[32mhello\x1b[0m")
    assert line["worker"] == os.getpid()
    assert "color_message" not in line
    assert "worker" not in format_line(JsonFormatter(worker_tags=False))


def test_uvicorns_parent_process_logs_json_through_the_log_config():
    """backend/Dockerfile passes app/log_config.json to Uvicorn, whose parent process
    otherwise prints plain `INFO: Started parent process` lines into the JSON stream."""
    script = (
        "import json, logging, logging.config\n"
        "logging.config.dictConfig(json.load(open('app/log_config.json')))\n"
        "logging.getLogger('uvicorn.error').info('Started parent process [1]',"
        " extra={'color_message': 'x'})\n"
    )
    done = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-c", script],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "LOG_WORKER_TAGS": "true"},
    )
    line = json.loads(done.stdout.strip())
    assert line["msg"] == "Started parent process [1]"
    assert line["logger"] == "uvicorn.error"
    assert isinstance(line["worker"], int)
    assert "color_message" not in line


# ---- pool leak watch and connection budget ---------------------------------------------------


def test_a_connection_held_too_long_is_reported_with_its_request_id(seeded, caplog):
    caplog.set_level(logging.WARNING, logger="eos.db")

    async def main() -> None:
        engine = make_engine(seeded, seeded.database_url, "eos-test:leakwatch")
        watch = LeakWatch(engine, threshold_s=0.1)
        token = request_id_var.set("req_leak01")
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                await asyncio.sleep(0.2)
                watch.check()  # still out: the real-leak warning
                watch.check()  # ...only once
            assert watch.out == {}
        finally:
            request_id_var.reset(token)
            watch.stop()
            await engine.dispose()

    asyncio.run(main())
    lines = [(r.getMessage(), r.__dict__.get("request_id")) for r in caplog.records]
    assert lines == [
        ("db connection checked out for more than 0.1 s", "req_leak01"),
        ("db connection returned after a long checkout", "req_leak01"),
    ]


def test_short_checkouts_are_quiet(seeded, caplog):
    caplog.set_level(logging.WARNING, logger="eos.db")

    async def main() -> None:
        engine = make_engine(seeded, seeded.database_url, "eos-test:leakwatch")
        watch = LeakWatch(engine, threshold_s=5)
        try:
            for _ in range(3):
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            watch.check()
        finally:
            watch.stop()
            await engine.dispose()

    asyncio.run(main())
    assert [r for r in caplog.records if r.name == "eos.db"] == []


@pytest.mark.parametrize(("workers", "level"), [(2, logging.INFO), (8, logging.WARNING)])
def test_the_connection_budget_warns_when_workers_cannot_fit(seeded, caplog, workers, level):
    caplog.set_level(logging.INFO, logger="eos.db")
    settings = seeded.model_copy(update={"api_workers": workers})

    async def main() -> dict:
        engine = make_engine(settings, settings.database_url, "eos-test:budget")
        try:
            return await connection_budget(engine, settings)
        finally:
            await engine.dispose()

    budget = asyncio.run(main())
    per_worker = settings.db_pool_size + settings.db_max_overflow + 1
    assert budget["total"] == workers * per_worker
    assert budget["max_connections"] >= 100
    record = next(r for r in caplog.records if r.name == "eos.db")
    assert record.levelno == level


def test_log_level_governs_uvicorns_own_lines_too(capsys):
    """Uvicorn sets its loggers to INFO itself; LOG_LEVEL=warning must still quiet them."""
    from app.logging import setup_logging

    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.setLevel(logging.INFO)  # what Uvicorn's own config does
    try:
        setup_logging("warning", stream=sys.stdout)
        uvicorn_error.info("Started server process [9]")
        uvicorn_error.warning("Invalid HTTP request received.")
    finally:
        root.handlers[:], _ = saved
        root.setLevel(saved[1])
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    assert [line["msg"] for line in lines] == ["Invalid HTTP request received."]


def test_the_budget_check_names_its_connection(seeded, monkeypatch):
    """Every connection carries an application name (plan 3.12), the preflight's too."""
    import types

    import app.db
    from app.preflight import _budget

    seen = []

    async def record_name(engine, _settings):
        async with engine.connect() as conn:
            seen.append((await conn.execute(text("SHOW application_name"))).scalar_one())

    monkeypatch.setattr(app.db, "connection_budget", record_name)
    asyncio.run(_budget(types.SimpleNamespace(state=types.SimpleNamespace(settings=seeded))))
    assert len(seen) == 1 and seen[0].startswith("eos-api:preflight:")
