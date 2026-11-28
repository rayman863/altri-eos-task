# EOS Level 10 Meeting app

A Ninety/EOS-style weekly team tool: Scorecard, Rocks, To-Dos, Issues and a live Level 10 Meeting that several people follow from their own browsers. Next.js 16 + TypeScript + shadcn/ui + Tailwind, FastAPI, Postgres 17 with Alembic migrations, Redis, all started by `docker compose up`.

**Also read:** [docs/DECISIONS.md](docs/DECISIONS.md) (the five decisions) · [docs/API_CONTRACTS.md](docs/API_CONTRACTS.md) · [docs/DB_SCHEMA.md](docs/DB_SCHEMA.md) · [docs/SCALING.md](docs/SCALING.md) (1,000 companies) · [docs/FUTURE_WORK.md](docs/FUTURE_WORK.md) (unbuilt bonuses) · [rules_report.json](rules_report.json) · [artifacts/](artifacts/) (failing-test trace)

## Run it

Needs Docker Desktop 4.27+ (or Engine 25+ with Compose v2), about 6 GB of free disk, and free ports 3000, 8000, 8080, 5433 and 6379.

```
docker compose up
```

The first run builds the images (a few minutes). Migrations and the seed run automatically, then a banner prints every address and the seeded users. Open **http://localhost:3000** and pick a user (no passwords: the brief's user switcher). For the two-browser meeting, use `u3` Casey Cho in one window and `u2` Blake Brooks in a private window. `docker compose logs info` shows the banner again; `docker compose down -v` starts over from a fresh seed.

| What | Where |
|---|---|
| App | http://localhost:3000 |
| API and its docs | http://localhost:8000, `/docs`, `/redoc` |
| Logs (Dozzle): one JSON line per request, with request id and worker | http://localhost:8080 |
| Postgres, Redis | `localhost:5433`, `localhost:6379` (credentials in `.env.example`) |

Every setting has a default; copy `.env.example` to `.env` to change one. Each platform extra can be switched off there (`API_WORKERS=1`, `WEB_RUNNER=node`, `CACHE_ENABLED=false`, `CSP_MODE=off`, `RATE_LIMIT_ENABLED=false`, `READ_ONLY_FS=false`, `GZIP_ENABLED=false`, `LOG_WORKER_TAGS=false`, `POOL_LEAK_WATCH=false`); the browser tests pass with all of them off.

## Tests

One command, unattended: **`make test`**. Without `make` (Windows), the same steps:

```
docker compose run --rm tests                                              # 494 rule, DB, API, cache, security tests
docker compose run --rm -e CACHE_ENABLED=false tests pytest tests/api      # the API tests again, cache off
docker run --rm -v "${PWD}/frontend:/app:ro" -w /app node:24.22.3-alpine npm run --silent test:server   # 10 web server tests
docker compose --profile e2e build e2e-seed web-e2e
docker compose run --rm e2e                                                # 10 Playwright tests, two browsers
docker compose --profile e2e stop api-e2e web-e2e
```

- **Rules:** every rule of brief 2.6 at its boundaries, including daylight saving, half-up rounding (8.25 → 8.3) and exactly 90 %.
- **API:** every route against every role (a route-table test fails any route added without a guard), 20 concurrent "Make it an Issue" clicks making exactly one Issue (for a cell, a Rock and a To-Do), CSRF, validation, rate limits, live updates across two real API processes, the cache, and an OpenAPI contract drift check.
- **Browser:** two browsers in one meeting (start, join, follow every section within 2 s, reload mid-meeting, rate, end, both on the summary, then listed first under Past meetings), live score edits, Make it an Issue (from a cell, a To-Do and a Rock), XSS shown as text, the Observer's read-only view, server-rendered HTML, two lost-update cases. Any CSP violation fails a test.
- **Fixture and clock:** all tests run at `APP_NOW=2026-11-11T15:00:00Z` on a frozen clock, against a separate `eos_test` database that is truncated and reseeded for every test, so they never touch the demo data. Rate limits are off except in their own tests. The browser tests run on their own stack, reseeded per run.
- **Failure artifact:** [artifacts/e2e-failure-trace.zip](artifacts/e2e-failure-trace.zip), from a deliberately broken run ([how](artifacts/README.md)); open it at https://trace.playwright.dev.

**Rules report** (JSON on stdout; it seeds its own scratch database, never the demo one):

```
docker compose --progress quiet run --rm --build rules-report
docker compose --progress quiet run --rm --build -e APP_NOW=2026-11-18T15:00:00Z rules-report
```

## Assumptions

- **Time:** "now" is `APP_NOW`; the app starts there and ticks forward on one clock shared by every process (tests freeze it). Weeks run Monday to Sunday in the company's time zone (America/Chicago). Rules are evaluated as of now: an Issue solved after now is still open.
- **Owners:** To-Dos and Issues can be owned by the team's non-Observer members and any Admin. Admins see every team; Observers read their teams and join meetings, but change nothing and don't rate.
- **Scores:** any of the 13 weeks shown can be edited or cleared. Last save wins, unless the client sends the version it saw (the web app does): then a stale save is refused with the current value.
- **Meetings:** one active meeting per team; whoever starts it facilitates and alone moves it along or ends it. Ending freezes the summary; later edits never change it.
- **Access errors:** a team you can't access is `403`, even for an id that doesn't exist, so ids can't be probed (Admins get `404`).
- **New To-Dos** from an Issue are due in 7 days, company time.
- **Past meetings:** the team page lists ended meetings, each linking to its frozen summary. The brief puts a meeting history page out of scope; this small list is an extra, added so the seeded summaries can be found without typing their URL.

## Known limitations

| Accepted for this review stack | Production would use |
|---|---|
| User switcher, no passwords; `/auth/users` and `/docs` are public | OIDC or SSO per company; docs behind auth |
| Payload logging on; Dozzle needs the Docker socket (`:ro` doesn't limit the Docker API) | Payload logging off; central logging without socket access |
| Plain HTTP on localhost, so cookies aren't `Secure` | TLS with HSTS, `COOKIE_SECURE=true` |
| One company; an Admin sees every team | Company-scoped roles, row-level security ([docs/SCALING.md](docs/SCALING.md)) |
| Users, teams, Measurables and Rocks come from the seed only | Admin screens |

Also: no pagination (one company's data); at most 5 live streams per user on each API worker; every browser on the host counts as one address for the sign-in limit (10 a minute). Two bonus items aren't built (the activity log and signed Next.js-to-API requests); [docs/FUTURE_WORK.md](docs/FUTURE_WORK.md) says how I'd build them.

## Security

One access policy for every route, checked before any cache lookup; signed `HttpOnly` session cookies that logout invalidates everywhere; CSRF protection (required header, `Origin` check, JSON-only writes); strict, size-limited input validation; least-privilege database roles; a per-request nonce Content-Security-Policy; rate limits; non-root containers with read-only filesystems and no Linux capabilities. Dependency audit (`make audit`): no known vulnerabilities in the API's runtime packages (`pip-audit`) or the web app's and PM2's (`npm audit --omit=dev`, after a lockfile-only fix of a build-time `minimatch` advisory).

## AI tools used

Built with **Claude Code** (Anthropic's Claude, in the Claude desktop app), with me directing it. It drafted the plan with me ([DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md); its decision log records every choice and who made it), then implemented each phase: backend, frontend, tests, Docker setup and these docs. After every phase it reviewed the work and ran a cohesion check across all earlier phases; the fixes are in the plan's revision log. I made the product and architecture calls (the real-time transport, frozen summaries, the log viewer, PM2, Redis, the security scope, which bonus items to build), reviewed the results, and ran the app myself in two browsers.
