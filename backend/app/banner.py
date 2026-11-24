"""Startup banner: `python -m app.banner` (plan 3.11).

Printed by the one-shot `info` service once api and web are healthy. Plain ASCII so it
renders in Windows PowerShell 5.1. The user table is filled from the database in Phase 2.
"""

from app.config import get_settings

WIDTH = 64


def render() -> str:
    s = get_settings()
    host = s.public_host
    rule = "=" * WIDTH
    thin = "-" * WIDTH
    lines = [
        rule,
        f" EOS L10 app is ready        APP_NOW {s.app_now} ({s.app_clock_mode})",
        thin,
        f" App (Next.js)   http://{host}:{s.web_port}",
        f" API (FastAPI)   http://{host}:{s.api_port}    uvicorn x{s.api_workers}",
        f" API docs        http://{host}:{s.api_port}/docs    ReDoc: /redoc",
        f" Logs (Dozzle)   http://{host}:{s.logs_port}",
        f" Postgres        postgresql://eos_owner:<EOS_OWNER_PASSWORD>@{host}:{s.db_port}/eos",
        thin,
        " Sign in: open the app and pick a seeded user (no passwords).",
        " Seeded users are listed here once Phase 2 loads the seed.",
        thin,
        " Show this again:  docker compose logs info",
        rule,
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(render(), flush=True)
