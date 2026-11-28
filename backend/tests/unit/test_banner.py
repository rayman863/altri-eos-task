"""The startup banner's process labels (layers L1 and L2)."""

import pytest

from app.banner import render, web_processes
from app.config import Settings


@pytest.fixture(autouse=True)
def _default_process_counts(monkeypatch):
    """The labels below are for the defaults, whatever the shell running pytest exports."""
    for name in ("API_WORKERS", "WEB_RUNNER", "WEB_INSTANCES"):
        monkeypatch.delenv(name, raising=False)


def settings(**env: str) -> Settings:
    return Settings(**env)  # the rest from the environment (the tests container's)


@pytest.mark.parametrize(
    ("env", "label"),
    [
        ({}, "pm2 cluster x2"),
        ({"web_instances": "4"}, "pm2 cluster x4"),
        ({"web_instances": "max"}, "pm2 cluster, one worker per CPU thread"),
        ({"web_runner": "node", "web_instances": "4"}, "node x1"),
    ],
)
def test_web_label(env, label):
    assert web_processes(settings(**env)) == label


def test_values_only_the_web_server_understands_never_stop_the_api():
    """The API reads these settings too (for the banner), so they must not fail validation:
    the web container is the one that checks them (frontend/start.sh)."""
    s = settings(web_runner="something-else", web_instances="max")
    assert s.web_instances == "max"


def test_banner_shows_both_process_counts():
    text = render(settings(api_workers=2), users=None)
    assert "pm2 cluster x2" in text
    assert "uvicorn x2" in text
