"""Startup check, run once before Uvicorn starts its workers: `python -m app.preflight`.

With `--workers N` (layer L1, plan 3.13), Uvicorn's parent process restarts any worker
that exits, at once and forever, and never exits itself. So a worker that can't start
(invalid settings, no database, missing tables) would restart in a loop, a traceback per
attempt, inside a container that stays up, instead of stopping it with one clear error
the way a single process does.

This builds the app (which reads and validates the settings) and runs one worker's real
startup and shutdown (`lifespan` in app/main.py: database, clock anchor, LISTEN
connection) once, in the foreground. Exit code 0 lets the Dockerfile start Uvicorn; 1
stops the container with the error in its log. A worker that dies later, at run time, is
still restarted by Uvicorn's parent, which is what the parent is for.
"""

import asyncio
import logging
import sys

from fastapi import FastAPI

log = logging.getLogger("eos.preflight")


async def _start_and_stop(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        pass


def main() -> int:
    try:
        from app.main import app  # settings are read and validated here

        # The workers log their own startup in a moment; keep this run to its warnings
        # (such as "database not ready, retrying") and its result.
        logging.disable(logging.INFO)
        try:
            asyncio.run(_start_and_stop(app))
        finally:
            logging.disable(logging.NOTSET)
    except Exception:  # noqa: BLE001 - any failure means the workers would fail too
        log.exception("api preflight failed, so the api is not started")
        return 1
    log.info("api preflight passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
