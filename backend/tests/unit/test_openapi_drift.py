"""The committed openapi.json matches the API, so the frontend's generated types can't
drift from it (plan 3.17). Regenerate both with `make openapi`."""

import os
from pathlib import Path

from app.openapi_export import render


def committed() -> Path:
    root = os.environ.get("REPO_ROOT")  # the tests container mounts the repo at /repo
    return Path(root or Path(__file__).resolve().parents[3]) / "openapi.json"


def test_committed_openapi_matches_the_api():
    path = committed()
    assert path.is_file(), f"{path} is missing: run `make openapi`"
    assert path.read_text(encoding="utf-8") == render(), (
        "openapi.json is stale: run `make openapi` (it also regenerates the frontend types)"
    )
