"""Startup banner: `python -m app.banner` (plan 3.11).

Printed by the one-shot `info` service once api and web are healthy. Plain ASCII so it
renders in Windows PowerShell 5.1. Users come from the database (as eos_readonly), so the
list always matches what was actually seeded.
"""

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings

WIDTH = 64

USERS_SQL = text(
    """
    SELECT u.id, u.name, u.email, u.role,
           coalesce(string_agg(t.name, ', ' ORDER BY t.name), '') AS teams
    FROM users u
    LEFT JOIN memberships ms ON ms.user_id = u.id
    LEFT JOIN teams t ON t.id = ms.team_id
    GROUP BY u.id, u.name, u.email, u.role
    ORDER BY length(u.id), u.id
    """
)


async def seeded_users(database_url: str) -> list[tuple[str, str, str, str, str]]:
    engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"application_name": "eos-banner"}},
    )
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(USERS_SQL)).all()
    finally:
        await engine.dispose()
    return [
        (r.id, r.name, r.email, r.role, "all teams" if r.role == "admin" else r.teams) for r in rows
    ]


def _user_table(users: list[tuple[str, str, str, str, str]]) -> list[str]:
    header = ("ID", "Name", "Email", "Role", "Teams")
    widths = [max(len(row[i]) for row in [header, *users]) for i in range(4)]

    def line(row: tuple[str, ...]) -> str:
        cells = [row[i].ljust(widths[i]) for i in range(4)]
        return " " + "  ".join([*cells, row[4]])

    return [line(header), *(line(u) for u in users)]


def render(s: Settings, users: list[tuple[str, str, str, str, str]] | None) -> str:
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
        " Sign in: open the app and pick a user (no passwords).",
    ]
    if users:
        lines += _user_table(users)
        lines += [thin, " Two-browser demo: u1 in one window, u3 in a private window."]
    else:
        lines.append(" (Could not read the users from the database; see the migrate logs.)")
    lines += [" Show this again:  docker compose logs info", rule]
    return "\n".join(lines)


def main() -> None:
    settings = get_settings()
    try:
        users = asyncio.run(seeded_users(settings.readonly_database_url))
    except Exception:  # noqa: BLE001 - the banner must still print the endpoints
        logging.getLogger("eos.banner").exception("could not load users for the banner")
        users = None
    print(render(settings, users), flush=True)


if __name__ == "__main__":
    main()
