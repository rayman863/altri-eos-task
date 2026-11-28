# Development Plan: Altri Senior AI-First Software Engineer Assessment

Built from the assessment brief, the seed README, the seed data (`seed.json`) and the take-home email (all read from your open tabs on 2026-11-23). **Status: building. Phases 0 to 7 are done, so the graded core is complete, and so are platform layers L1 (two API workers) and L2 (PM2 cluster for web), both reviewed, and L3 (Redis cache), reviewed too, and L4 (security extras), reviewed too; see the revision log. Layer L5 and Phase 8 are next.**

| | |
|---|---|
| **Deadline** | Saturday 2026-11-28, 11:59 PM EST (= 2026-11-29 04:59 UTC) |
| **Availability** | 4 h per day Tue to Fri, ~4.5 h Saturday (decisions 22 to 24 and 31) |
| **Estimate** | Core ~21.5 h, including the 1 h Docker setup (done), the meeting snapshot, the compose startup banner, PM2, connection pooling, multi-worker API, the Redis cache, Dozzle stream separation, security hardening, gzip and ~0.25 h for layer switches, so ~20.5 h left: ~15.25 h graded core, ~4 h platform layers, ~1.25 h docs and video. Bonus work is ranked and only runs after the core is green (section 9) |
| **Build starts** | Tuesday 2026-11-24 (Monday went to planning and the Docker setup) |
| **Product** | A Ninety/EOS-style weekly team meeting tool: Scorecard (Measurables), Rocks, To-Dos, Issues, plus a live Level 10 Meeting |
| **Stack (mandated)** | Next.js + TypeScript + shadcn/ui + Tailwind, FastAPI, Postgres with migrations, `docker compose up` |

> **Budget warning:** the remaining work (~20.5 h) needs 4 h a day Tue to Fri plus ~4.5 h on Saturday (section 7), with no slack. The build order (section 5) puts every graded feature first, so a slip lands on the platform layers, which can ship switched off, rather than on graded work. It is well above the brief's own 10 to 14 h estimate, and the brief says a solid core beats a wide one. Bonus items only happen if phases finish faster than estimated. With AI help that is realistic, but plan for it not happening.

**Guiding rule from the brief:** "A solid core beats a wide, shaky one." Evaluation weights tell us where to spend the hours:

| Area | Weight | Plan emphasis |
|---|---|---|
| Data model and API design | 20% | Constraint-rich schema, one pure rules module, consistent documented API |
| Real-time, concurrency, rule correctness | 20% | Server-owned meeting state, DB-enforced no-duplicate Issues, rules report matches answer key |
| Usability | 15% | Meeting page readable under time pressure |
| Security | 15% | One central authz policy, tested route-by-route |
| Testing | 15% | One-command unattended suite, fixed clock |
| Frontend quality | 10% | Server-first rendering, typed API client, Server Actions with zod forms |
| Docs and video | 5% | README (2 pages max), 1-page decision record, 7-min video |

### Revision log

- **v36 (2026-11-28):** review of layer L4 with a cohesion check across Phases 0 to 7 and layers L1 to L4 (6 findings, all fixed, decision 49). Important, reproduced by a test first: logout counted as a write, so a user over the write limit got a 429 on logout while the web app dropped its cookie anyway, leaving the server-side session valid; logout is now never limited. Smaller: `/healthz` said `redis: off` with the cache off even though the rate limits still used Redis (it now pings through whichever layer uses it); a typo such as `CSP_MODE=Off` was silently ignored (start.sh now stops with exit 64, like the other web switches); the web image's files were owned by the user that runs them, so with `READ_ONLY_FS=false` the server could change its own code (now root-owned); the CSP E2E test could leave a browser open after a failure, holding a live stream against the next tests' limit; and the audit had no command (`make audit`). Cohesion run green: 443 backend tests, the API tests again with the cache off (176, 15 skip), 10 web server tests, 7 E2E with every layer on and 6 plus 1 skipped with L1 to L4 off, `ruff`, `tsc`, `eslint` clean, the rules report byte-identical under the read-only filesystem, the seed running read-only, and with Redis stopped every login and logout still went through (both the cache and the rate limiter logged their own breaker).
- **v35 (2026-11-28):** **layer L4 done** (decision 48). A per-request nonce Content-Security-Policy on every page (`frontend/src/proxy.ts`; the root layout waits for the request, so no page is prerendered without a nonce; `CSP_MODE=off` switches it off). Rate limits on Redis (`backend/app/ratelimit.py`, sharing the cache's pool code and breaker; fail open): 10 logins a minute per client address, 30 Make it an Issue and 120 other writes a minute per user, 429 `rate_limited` with `Retry-After`; the login page says what happened. Every container built from our images runs with a read-only root filesystem (a 64 MB `/tmp` tmpfs, where `PM2_HOME` already was), `no-new-privileges` and no Linux capabilities, as a non-root user (`READ_ONLY_FS=false` for debugging). Found while building it: zod 4 probes for `eval` support with `new Function`, which the policy blocks and browsers report as a violation on every page with a form; zod now runs jitless (`src/lib/zod.ts`, with a lint rule against importing zod directly). The E2E fixture now fails any test whose browsers saw a CSP violation. Dependency audit: `pip-audit` found nothing in the API's 28 runtime packages; `npm audit --omit=dev` found 4 moderate (a `minimatch` ReDoS under the `shadcn` CLI's `ts-morph`, build time only, not in the runtime image), fixed with a lockfile-only `npm audit fix`; PM2's lockfile is clean. 441 backend tests (6 new rate-limit tests), the API tests again with the cache off (174, 15 skip), 7 E2E with every layer on, and 6 plus 1 skipped (the CSP test) with L1 to L4 all off.
- **v34 (2026-11-28):** review of layer L3 with a cohesion check across Phases 0 to 7 and layers L1 to L3 (8 findings, all fixed, decision 47; none could serve stale or cross-team data). Keys now carry a hash of the API's source, so a rebuilt API never reads entries an older build wrote even when nothing reseeded. The stampede lock is released only by its owner (a compute that outlived its lock no longer deletes the next request's), and waiters stop waiting as soon as the computing request fails instead of sitting out the full second. The request log's `cache` field now describes the data the request asked for: the access-facts lookup every request makes no longer shows writes as `hit`. A user removed between the epoch lookup and the facts lookup is signed out instead of raising. The banner shows the Redis URL with `<REDIS_PASSWORD>` like the Postgres line, and `make test` also runs the API tests with the cache off (`make test-backend-uncached`). Cohesion run green: 435 backend tests with the cache on, the API tests again with it off (168, the 15 cache tests skip), 10 web server tests, 6 E2E with every layer on and again with L1 to L3 all off, the rules report byte-identical to the committed one, `ruff` clean; on the stack, 400 reads at 100-way concurrency all succeeded with no Redis error (399 hits), and the API stopped cleanly in 1.4 s with Redis down.
- **v33 (2026-11-28):** **layer L3 done** (decision 46): the Redis cache-aside read layer of 3.14 (`backend/app/cache.py`, `redis` service on `redis:8.2.3-bookworm` with a password, `redis==8.1.0`). Team read models are keyed by `cache_version`, reference data by a per-database generation that every seed replaces; keys carry the database name, so the demo and E2E stacks share one Redis safely. Entries built from future-dated rows expire when that moment comes; access facts are cached but the session epoch is not; `/healthz` reports `redis` and the per-worker `cache` counters, and request log lines carry `cache: hit | miss | bypass`. 433 backend tests with the cache on, 420 with it off (13 cache tests skip), 6 E2E both ways, 10 web server tests. Also this day: Docker Desktop lost its images and volumes when the C: drive filled up; the stack rebuilt from nothing with `docker compose up` (a clean-start check), and one Redis Alpine base layer stayed corrupted in the local image store, which is part of why the pin is the Debian variant.
- **v32 (2026-11-28):** review of layers L1 and L2 with a cohesion check across Phases 0 to 7 and both layers (9 findings, all fixed, decision 45). Two were important, both reproduced. (1) With `--workers 2`, a worker that cannot start (bad settings, no database) was restarted by Uvicorn's parent forever, a traceback each time, in a container that never exited; with one worker it exits 1. The image now runs `python -m app.preflight` (one worker's real startup and shutdown, once) before Uvicorn: a bad `APP_ENV=production` start now exits 1 in 2 s instead of looping. (2) `stream-shutdown.cjs` swallowed a stop signal that arrived before Next installed its own handlers (they come once the server listens), leaving a booting worker running until killed; it now exits 130/143 itself when it is the only handler. It also tracks stream responses instead of sockets, so a normal request on a keep-alive connection whose stream had ended is no longer cut off at a stop. Pre-existing, found on the way: a settings error printed the values it was given, so a short `SESSION_SECRET` or a database password could reach the logs (`hide_input_in_errors`). Smaller: the process-test fixture now stops both processes even if one hangs, the banner tests ignore the shell's `WEB_*`/`API_WORKERS`, `/healthz` docs list `worker`, the study guide's old `test:edge` command, and an empty stray `docs;C` folder. Cohesion run green: 420 backend tests, 10 web server tests, 6 E2E with 2+2 workers and again with both layers off, `ruff`, `tsc`, `eslint` clean; on the stack, web stop with two open streams 1.2 s, stop right after start about 1 s, `pm2 reload` under traffic 40 of 40 requests ok, API stop 1.6 s, a killed API worker replaced with 0 failed probes, demo data untouched.
- **v31 (2026-11-28):** **layers L1 and L2 done** (decision 44). L1: `API_WORKERS=2` by default; a real two-process test (`tests/api/test_processes.py`: two `uvicorn` processes started together share one clock anchor, a follower on one follows a meeting run on the other within 1 s, `SIGTERM` ends open streams at once); `/healthz` names the worker that answered. L2: `web` runs `pm2-runtime` in cluster mode with 2 workers (`ecosystem.config.cjs`, `start.sh` with the `WEB_RUNNER` switch, PM2 7.1.2 from its own lockfile, JSON logs with the worker id); the banner shows `pm2 cluster x2` and `uvicorn x2`. Found and fixed while building L2: stopping `web` with a live tab open waited for PM2's kill timeout (11 s; 25 s with the plain runner), because Next waits for open requests and a proxied SSE stream never ends; `stream-shutdown.cjs` hangs streams up on the signal (stop now 1.2 s). New `make test-web` runs the server-side Node tests (7). Green: 417 backend tests, 7 web tests, 6 E2E with 2+2 workers and with both layers off, ruff and eslint clean.
- **v30 (2026-11-28):** review of Phase 7 with a cohesion check across Phases 0 to 7 (8 findings, all fixed; the cohesion run was green: 408 backend tests, 6 E2E tests, `tsc` and `eslint` clean, demo data untouched). The E2E runner no longer shares the host's IPC namespace (`shm_size` instead), installs from an npm cache volume (`--prefer-offline`), and leaves its output deletable on Linux hosts while keeping the test exit status. `signIn` is now a fixture that closes every browser context it opened. Only `E2E_DEMO_FAILURE=trace-demo` breaks the meeting test on purpose (verified: `=1` is ignored and passes, `trace-demo` fails at the IDS step); the committed trace was regenerated with it (6.4 MB). The E2E specs are type-checked (`npm run typecheck`, also in `make lint`). `artifacts/README.md` shows PowerShell commands, and plan section 6 describes the E2E suite as built.
- **v29 (2026-11-28):** **Phase 7 done, graded core complete** (decision 43). Browser end-to-end tests with Playwright 1.65.1 (`e2e/`), run in Microsoft's Playwright image against an isolated stack (`e2e-seed`, `api-e2e`, `web-e2e` under the compose profile `e2e`: the `eos_test` database, a frozen clock, reseeded every run), so they never touch the demo data. Six tests: a live score edit across two browsers within 2 s (plus an invalid value refused in place), Make it an Issue in the UI, server-rendered HTML containing the Scorecard values, an XSS payload rendered as text in two browsers, the Observer's read-only view and a foreign team's access page, and the full two-browser meeting (start, auto-join, both follow Scorecard to IDS within 2 s, reload lands on the current section, rating, end, both on the summary). `make test` now runs the backend suite and then the E2E suite and stops the E2E stack afterwards (109 s in total, demo data unchanged). A deliberately broken run (`E2E_DEMO_FAILURE=1` blocks the teammate's live stream) produced the committed `artifacts/e2e-failure-trace.zip`. Found along the way: a score cell in edit mode hid its validation error; it now shows it under the input.
- **v28 (2026-11-27):** review of Phase 6 with a cohesion check across Phases 0 to 6 (7 findings, all fixed, decision 42). Two were important, both reproduced on the stack: open pages never resumed live updates after an API restart (EventSource treats the proxy's HTTP error as final), and a browser could set the client IP the API logs and rate-limits by (Next passed `X-Forwarded-For` through). Now `LiveRefresher` reconnects with a backoff (verified: after `docker restart eos-api-1` the page went back to *Live* and showed the next change), and `edge-headers.cjs`, preloaded into the Next server, replaces forwarding headers with the TCP peer and drops client request ids (verified: spoofed 6.6.6.6 / 7.7.7.7 now log the real address on both the SSR and `/api` paths). Also: refused forms keep the typed text, Start meeting shows why it failed, the Scorecard's Issue link works in the meeting, the To-Do section no longer fetches `/me`, and the OpenAPI drift test uses `REPO_ROOT`.
- **v27 (2026-11-27):** **Phase 6 done** (decision 41): the Next.js frontend, server-first. Login switcher (plain forms, work before hydration), `proxy.ts` gate, `(app)` layout with team switcher, team gate (403 page, 404), Team page with Scorecard, Issues (unsolved and solved), To-Dos and Rocks streamed in `<Suspense>`, Meeting page (agenda stepper, server-clock timer with over-time, facilitator controls, `AlertDialog` to end, Conclude with new To-Dos and rating, auto-join), summary page, and `LiveRefresher` (one `EventSource` per team, debounced `router.refresh()`). Writes are Server Actions with zod (also checked client-side), optimistic score cells, To-Do toggles, priorities and ratings. Typed client: `openapi.json` (repo root, `make openapi`) to `openapi-typescript` types and `openapi-fetch`, with a drift test. Walked through in a real browser: sign in, edit a score, live update from a second user within 1 s, start, join, advance, solve, add a To-Do, rate, end, summary; the Observer view is read-only and follows a meeting live, including auto-join and the jump to the summary when it ends. `tsc` and `eslint` clean; 408 backend tests green.
- **v26 (2026-11-27):** review of Phase 5 with a cohesion check across Phases 0 to 5 (7 findings, all fixed, decision 40). The important one: logout revoked the cookie but not the user's open SSE streams, which kept receiving events; logout now sends a user-scoped `NOTIFY` and every worker ends that user's streams (verified live through the proxy: the stream ended at logout instead of running on). Also: event ids never go back after a snapshot; the listener resyncs streams on its first connect too; losing the stream-cap race ends the stream with an `error` event instead of an exception; a queue overflow keeps a pending `CLOSE`; `/healthz` reports `realtime` (listener status, open streams) and no longer crashes on a `NullPool` engine; plan 3.12 item 8 describes the SIGTERM hook. 407 tests green.
- **v25 (2026-11-27):** **Phase 5 done** (decision 39): meeting start, join, advance (compare-and-set), end (freezes the summary in the same transaction), rating and summary endpoints, and the team SSE stream (`app/realtime.py`): every team write sends `pg_notify` inside its transaction, each worker's dedicated `LISTEN` connection feeds an in-process hub, and streams send `snapshot`, `team.changed`, `meeting.state`, `meeting.ended` and a 15 s heartbeat. Verified live through the Next.js proxy: a follower saw start, advance and end about 300 ms after each command (including curl's own round trip); a stream stayed open 135 s idle with pings every 15 s and still delivered; three open streams held no pool connection; streams end 1 s after `SIGTERM` (was 21 s). 46 new tests (399 total) include two-worker fan-out, rolled-back writes sending nothing, listener reconnect with resync, and the frozen summary not changing after later edits.
- **v24 (2026-11-26):** review of Phase 4 with a cohesion check across Phases 0 to 4 (11 findings, all fixed, decision 38). The important one: business time came from a per-process ticking clock, so after an API restart (or between two workers) rows stamped later looked "in the future" and the as-of-now rules hid them, e.g. a To-Do marked done came back as overdue. The shared `clock_anchor` row now gives every process and every restart one clock (pulled forward from Phase 5). Also: Make it an Issue returns an open Issue even after its week left the Scorecard; the ON CONFLICT race path and the DB error mapper are tested (connection loss is now 503); logout ends every session of the user (migration `0004`, `users.session_epoch`); OpenAPI lists Make it an Issue's 200; request logs carry `user_id`; `WEB_ORIGIN` is a list that follows `WEB_PORT`/`PUBLIC_HOST`; the test client no longer waits an hour for a disconnect; the wall-clock guard can't be fooled by `datetime` imported as `clock`; the contracts say what is deferred.
- **v23 (2026-11-26):** **Phase 4 done** (decision 37): every endpoint in `docs/API_CONTRACTS.md` sections 3 to 8 (session, teams, Scorecard, Make it an Issue, Issues, To-Dos, Rocks) behind one access policy (`app/authz.py`), with the signed session cookie, CSRF header + `Origin` check, JSON-only writes, the 64 KB body limit, API security headers, DB-error mapping by constraint name, and the `cache_version` bump as the first statement of every team write. 112 new tests drive the real app over pure ASGI against `eos_test`: the route-table authz test (every OpenAPI operation, as anonymous, Observer and other-team member), the contract examples, validation and mass-assignment, CSRF, and 20 concurrent Make it an Issue clicks ending in exactly one Issue. Also fixed: the request logger's trusted-proxy DNS lookup for `web` cost up to 4 s whenever `web` wasn't running (API healthchecks during startup, every test app); it now runs only for requests that carry proxy headers and is capped at 0.5 s. 317 tests green.
- **v22 (2026-11-26):** **Phase 3 done** (decision 36): `python -m app.rules_report` in the seed README's format, run as `docker compose --progress quiet run --rm --build rules-report` (`make rules-report` regenerates the committed file safely; section 6). It migrates, wipes and seeds its own `eos_report` database, then recomputes everything with the pure rules, so the demo data is never touched. `rules_report.json` is committed and matches every section 4 oracle. Tests prove the bytes are reproducible: a pure build from `seed.json`, the database path and the real command all produce the same file, the report's meetings equal the frozen snapshots, and an earlier or later `APP_NOW` moves the window and drops meetings that haven't happened yet. Also fixed: the `tests` service's unquoted `APP_NOW` reached the container as `2026-11-11 15:00:00 +0000 UTC` (YAML timestamp). 205 tests green.
- **v21 (2026-11-25):** review of Phase 2 with a cohesion check across Phases 0 to 2 (9 findings, all fixed, decision 35): the request session now commits before the response (`DbSession`, dependency scope `"function"`); the seed runs once per database, so deleted rows stay deleted; migration `0003` adds the Rock and To-Do open-Issue unique indexes and pins `search_path` on the trigger functions; `app/constraints.py` holds every DB rule name the API maps, checked against the database by a test; `decimal_str` formats API scores and goals; snapshots read the stored `scorecard_week`; an un-ended seed meeting loads as active; test connections are named `eos-test`; schema doc names match the code. 188 tests green.
- **v20 (2026-11-25):** review of Phases 0 and 1 with a cohesion check (9 findings, all fixed: rater-trigger spec vs seed, rate-limit IP source, JSON encoding of ratings, middleware tests, contract paths and codes, stale `make up` text, root-owned test caches, Docker 25+ note, wall-clock guard). **Phase 2 done** (decision 34): models with every constraint, migration `0002` with role triggers, idempotent seed with frozen snapshots for `mt1`/`mt2`, banner users from the database, request-scoped sessions, `/healthz` pool counters. 168 tests green (rules, unit, and DB tests against `eos_test`).
- **v19 (2026-11-25):** **Phase 1 done** (decision 33). Pure rules module in `backend/app/rules/`, clock service in `backend/app/clock.py`, 119 tests green: every rule with its boundaries, every row of section 4 against `seed.json`, and a check that nothing but `clock.py` reads the wall clock. Tests run in a `test` image via `docker compose run --rm tests` (or `make test`).
- **v18 (2026-11-25):** Phase 0 review fixes, each verified against the running stack. Unhandled 500s now carry the request id. Fonts come from the local `geist` package, not Google. Healthchecks probe every 2 s while starting and every 30 s after, with `/healthz` logged at debug. Log bodies are capped at 8 KB. Request ids and forwarded IPs are trusted only from the `web` proxy (last `X-Forwarded-For` entry). The backend image is built once. Stop grace period is 25 s. `eos_app` can't touch `alembic_version`. `LOG_LEVEL` is validated. The init script is executable. `make up` waits for the banner instead of using `--wait`.
- **v17 (2026-11-25):** **Phase 0 done** (decision 32). Stack verified with `docker compose up`. Implementation notes folded in: pinned versions, Next 16's `proxy.ts` (was `middleware.ts`), Cache Components off, Postgres host port 5433 (a local Postgres owns 5432 on the dev machine).
- **v16 (2026-11-24):** review pass (decision 31). Build reordered: graded core first (Phases 0 to 7), then platform layers L1 to L5 behind switches, then docs and video; schedule re-cut with a Friday "graded core complete" check and a Saturday guard. Seven seams fixed: team-row lock order, section 9 core scope, signing placement after the server-first rewrite, `meeting.state` wording, Redis-free seeding for tests and the report, cut-list reference, activity triggers in test and report databases.
- **v15 (2026-11-24):** activity log now captures every data table through a generic trigger (decision 30), with actor context from transaction-local settings, a noise filter and a coverage test; the Admin page gets 9 filters, full-text search and commit-style grouping. Bonus estimate ~5.5 h.
- **v14 (2026-11-24):** activity log (3.18, decisions 28 and 29) replaces the audit-trail bonus: separate `eos_activity` database, transactional outbox, background worker for writes and reads, Admin-only `/admin/activity` page with git-style diffs. Schema doc, API contracts, compose, connections, roles and frontend routes updated.
- **v13 (2026-11-24):** API contracts in `docs/API_CONTRACTS.md` (decision 27): conventions, error envelope and codes, access levels, every endpoint with seed-based examples, meeting state object, frozen summary format, SSE events, health. `GET /teams/{id}/owners` folded into `GET /teams/{id}`; `/me` now returns the server clock.
- **v12 (2026-11-24):** frontend made server-first (3.17 rewritten, decision 26): Server Components with streamed sections, Server Actions for writes, `router.refresh()` for live updates, client islands listed one by one, TanStack Query dropped. Related fixes: CSRF header now set server-side, login rate limit uses the forwarded IP, SSR check added to E2E, refresh-latency risk added.
- **v11 (2026-11-24):** frontend architecture (3.17, decision 25): routes, server-side auth gate, folder layout, shared sections, query keys, mutations and errors, typed client with a drift check, one SSE stream per team, timer, meeting page, forms, time zone display, permissions, states and accessibility, plus a data-flow diagram.
- **v10 (2026-11-24):** Next.js to FastAPI traffic (3.16, decision 24): gzip in core with SSE excluded; HMAC request and response signing with boot-time LRU key cache, replay protection and signed SSE events designed as bonus rank 5. Schedule updated to ~20.25 h left, Saturday ~4.25 h.
- **v9 (2026-11-24):** security hardening (3.15, decision 23): session cookie attributes, three-layer CSRF protection, mass-assignment and input limits, CSP and headers, rate limits, least-privilege Postgres roles (also in `docs/DB_SCHEMA.md`), container hardening, supply-chain checks, security tests. Core now ~20 h left.
- **v8 (2026-11-24):** schedule locked to 4 h days Tue to Fri plus 2.5 h Saturday (decision 22).
- **v7 (2026-11-24):** Redis cache layer (3.14, decisions 18, 19, 21): cacheable items, never-cached paths, cache keys versioned from `teams.cache_version` in Postgres so Redis can never serve stale data, stampede guard, failure fallback, Redis on its own port. Dozzle shows backend and frontend as separate streams with PM2 and Uvicorn workers tagged (3.10, decision 20). Schema doc updated and re-tested. Core now ~18.5 h left, with two schedule options.
- **v6 (2026-11-24):** schedule re-cut from Tuesday (Monday had no build work). 3 h Tue to Fri plus a 4.5 h Saturday, end-of-day checks, three ways to make it fit, deadline in local time, Thanksgiving note.
- **v5.1 (2026-11-24):** decision 16 (Uvicorn `--workers`, default 2) confirmed.
- **v5 (2026-11-23):** DB schema diagram in `docs/DB_SCHEMA.md` (decision 17). Connection pooling, pool lifecycle and application names (3.12, decision 15). API scaling with Uvicorn workers (3.13, decision 16, proposed), which makes `LISTEN/NOTIFY` and a DB-stored clock anchor required. Hours, schedule, cut list, tests and risks updated.
- **v4 (2026-11-23):** `web` runs under `pm2-runtime` in cluster mode (decision 14). Web healthcheck moved to `/healthz`, because `/api/*` is proxied to FastAPI. Added the SSE-through-proxy risk.
- **v3 (2026-11-23):** Docker prerequisite done. Added the compose stack and startup banner (3.11, decision 13): Postgres, frontend and backend on separate ports plus logs and API docs, automatic migrate + seed, endpoints and users printed on startup. Seed now inserts missing rows only (restarts keep your edits), tests use a separate `eos_test` database, and the rules report seeds its own scratch database.
- **v2 (2026-11-23):** open questions answered (section 1). Added the Docker prerequisite (section 0), debug log viewer (3.10), implemented meeting snapshots (3.9), ranked bonus list (9). Review fixes: hour total corrected, Make it an Issue now checks the cell is off track, To-Do due date rule, start-meeting conflict response, rules report at other dates, Windows has no `make`, and Dozzle's Docker socket risk.
- **v1 (2026-11-23):** first draft.

---

## 0. Prerequisite: local Docker (blocker, you do this)

Decision: **fix local Docker**. These are system settings, so you run them yourself.

Tooling status (re-checked 2026-11-23, second check):

| Tool | Windows | WSL2 Ubuntu |
|---|---|---|
| CPU virtualization (AMD Ryzen 7 5800H) | Enabled in firmware, hypervisor running | n/a |
| WSL2 | **Working** (kernel `6.6.87.2-microsoft-standard-WSL2`). The earlier `HCS_E_HYPERV_NOT_INSTALLED` error is gone | Ubuntu distro, WSL version 2 |
| Docker / Compose | **Working**: Docker Desktop 4.100.0, Engine 29.9.3 (linux/amd64), Compose v5.7.1, `hello-world` runs | Not checked (enable WSL integration in Docker Desktop if wanted) |
| Python | Windows Store stub only | Python 3.12.3 |
| Git | 2.45.1 | not checked |
| Node / npm | v24.16.0 / 11.13.0 | not checked |
| `uv`, `pnpm`, `make` | Not installed | `make` not installed |

Steps:

1. ~~Enable CPU virtualization in BIOS/UEFI.~~ Done (firmware reports enabled).
2. ~~Admin PowerShell: `wsl --install --no-distribution`, then reboot.~~ Done (WSL2 boots Ubuntu).
3. ~~Install Docker Desktop (`winget install Docker.DockerDesktop`).~~ Done.
4. ~~Verify `docker compose version` and `docker run --rm hello-world`.~~ Done. Gotcha: a terminal opened **before** the install keeps the old PATH, so `docker` is "not recognized" and image pulls fail with `docker-credential-desktop: executable file not found`. Fix: open a new terminal (or restart the editor/app hosting it).
5. Optional, for editor tooling only (everything else runs in containers): Python 3.12 and `uv` on Windows (or use the WSL Python 3.12.3), and `make` (`winget install ezwinports.make`, or `sudo apt install make` in WSL).

Prerequisite complete. Section 0 no longer blocks Phase 0.

---

## 1. Confirmed decisions (answered 2026-11-23)

| # | Question | Answer | Consequence for the plan |
|---|---|---|---|
| 1 | Where to develop (no Docker locally) | **Fix local Docker** | Section 0 prerequisite. Done: WSL2 and Docker Desktop both working |
| 2 | "The working app": hosted demo or repo only | **Repo + `docker compose up` only** | No deploy work. The video shows the app running |
| 3 | Real-time transport | **SSE + REST** | Section 3.7. Defend it in the decision record |
| 4 | Sign-in | **Seeded user switcher** | Signed httpOnly cookie, no passwords (3.5) |
| 5 | To-Do owner choices | **Team's non-Observer members + all Admins** | Same rule for Issue owners. Enforced in API and DB |
| 6 | Time available | **2.5 to 3 h per day, Mon to Fri**, later raised to 4 h Tue to Fri (decision 22) | Schedule in section 7 |
| 7 | Bonus items wanted | **All four:** lost-update protection, 1,000-companies note, Issue from Rock/To-Do, audit trail | Ranked in section 9, only after the core is green. The audit trail became the activity log (decision 28) |
| 8 | New request | **Debug log viewer** on its own port showing every API request and response payload plus application errors | Section 3.10. Built in Phase 0 because it pays back in every later phase |
| 9 | Log viewer: build or reuse | **Dozzle + structured JSON logs** | ~30 min, no custom UI |
| 10 | Log viewer exposure | **Always on** with `docker compose up` (bound to 127.0.0.1, secrets redacted) | Document it under security notes in the README |
| 11 | Past meeting summaries | **Implement the frozen snapshot** (not describe-only) | Section 3.9, +0.5 to 0.75 h in Phase 5 |
| 12 | Overflow handling | **Rank bonuses, stop at the deadline** | Unfinished bonus items get a short "how I would do it" note instead |
| 13 | New request: what `docker compose up` does | **Postgres, frontend and backend each on its own port, plus logging and API docs; migrations and seed run automatically; the terminal prints endpoints and login details when ready** | Section 3.11. Phase 0 grows by 0.5 h |
| 14 | New request: how `web` runs | **PM2 cluster mode** | Section 3.11 notes. `pm2-runtime`, 2 workers by default. Phase 0 grows by 0.25 h |
| 15 | New request: DB connection handling | **Managed connection pooling, pool lifecycle, per-component Postgres `application_name`** | Section 3.12. Phase 2 grows by 0.5 h |
| 16 | Your question: easy, valid way to scale FastAPI | **Uvicorn `--workers` (`API_WORKERS`, default 2)**, confirmed 2026-11-24 | Section 3.13. Makes `LISTEN/NOTIFY` and the shared clock anchor required. Phase 5 grows by 0.5 h |
| 17 | New request: DB schema diagram for review on GitHub | **Mermaid ER diagram in `docs/DB_SCHEMA.md`**, plus focused views, constraints, triggers, indexes | Render-tested in Mermaid 10.9.1 and 11.4.1: all 4 diagrams parse, all 16 tables appear |
| 18 | New request: cacheable items and a Redis layer between backend and DB | **Cache-aside Redis, cache keys versioned from Postgres** | Section 3.14 |
| 19 | New request: Redis boots on its own port with `docker compose up` | **Yes: `127.0.0.1:6379`, no profile, healthchecked, listed in the banner** | Section 3.11 table |
| 20 | New request: Dozzle shows backend logs and frontend PM2 logs separately | **Separate container streams with Dozzle names and groups; PM2 and Uvicorn workers tagged inside each stream** | Section 3.10. Phase 0 grows by 0.25 h |
| 21 | Redis scope | **"All safe parts of both core and bonus"**, read as: build every Redis piece (reference data, summaries, team read models, stampede guard) as core, in a form that cannot serve stale data. Cache versions moved from a Redis counter into `teams.cache_version` in Postgres to achieve that | Section 3.14. Core grows by ~1.75 h |
| 22 | Schedule for ~18.5 h of remaining core | **4 h days Tue to Fri, 2.5 h Saturday** (confirmed 2026-11-24) | Section 7. Thursday checkpoint. Saturday later grew to ~4.25 h (decisions 23 and 24) |
| 23 | Security hardening ("security first") | **CSRF (SameSite + custom header + Origin), JSON-only writes, strict validation and body limits, CSP and security headers, rate limits, least-privilege DB roles, non-root containers, dependency audit** | Section 3.15. +1.5 h (Phase 0 +0.5, Phase 4 +1.0) |
| 24 | New request: hash (salted, via env) and gzip all frontend-backend traffic, cache the salts/hashes at boot | **Gzip in core. HMAC-SHA256 signing of Next.js server to FastAPI requests and responses as bonus rank 5**, keys derived once at boot into an LRU, unsigned direct calls rejected with a proxy path and signing helper documented | Section 3.16. Gzip +0.25 h core; signing ~2 h bonus. Hashing proves integrity, it does not hide data; encryption was offered and not chosen |
| 25 | Frontend structure (planning request) | **Server components for the auth gate, client feature sections on TanStack Query with one key factory, typed client generated from a committed `openapi.json`, one SSE stream per team feeding the query cache** | Section 3.17. Changes the API: SSE moves from `/meetings/{id}/events` to `/teams/{id}/events`, and `/me` returns the company time zone. No hour change; Phase 6 (3.0 h) is now the tightest estimate. TanStack Query part superseded by decision 26 |
| 26 | New request: server-side rendering wherever possible, client components only where required | **React Server Components by default; Server Actions for all writes; `router.refresh()` on live events; client islands only for interactivity. TanStack Query dropped** | Section 3.17 rewritten. No hour change. Login rate limit now reads the forwarded client IP (3.15) |
| 27 | API contracts (planning request) | **`docs/API_CONTRACTS.md`:** one error envelope with 25 named codes, access level per endpoint, decimals as strings, server-computed values only, `/me` carries the server clock, eligible owners folded into `GET /teams/{id}`, SSE event formats with `cache_version` as event id | Section 3.5 links it. No hour change; Phase 4 tests take their expected values from its examples |
| 28 | New request: activity log in a separate database on the same cluster, with a dedicated background worker for its writes and reads | **`eos_activity` database, transactional outbox in the main database, worker container draining it with `SKIP LOCKED` and serving reads over an internal endpoint. Bonus rank 4, replacing the audit trail. Reads are Admin only** | Section 3.18. ~4 h bonus; core schedule unchanged |
| 29 | New request: activity UI as its own Admin-only page with a git-like before/after diff per activity | **`/admin/activity`, server-rendered, field-level `-`/`+` diff lines plus word-level diff for long text, expandable per event** | Section 3.18; included in the ~4 h |
| 30 | New request: log all data tables of the main database; filters and search on the activity page | **One generic `SECURITY DEFINER` row trigger (plus a truncate trigger) on every data table writes the outbox; actor and request context passed as transaction-local settings. Page gets 9 filters, full-text search with `websearch` syntax and highlighting, and transaction grouping like git commits** | Section 3.18 rewritten. Bonus estimate 4 h to ~5.5 h |
| 31 | Plan review: fix the seams and reorder the build | **Graded core first (Phases 0 to 7), then platform layers L1 to L5 behind config switches, then docs and video. Seven fixes: team-row lock order, core scope in section 9, signing in the server-side client, `meeting.state` wording, seed without Redis for tests and the report, cut-list reference, activity triggers in test and report databases** | Sections 5 and 7 rewritten; 3.14, 3.15, 3.16, 3.18, 8, 9 and `docs/DB_SCHEMA.md` fixed. ~20.5 h left, Saturday ~4.5 h |
| 32 | Phase 0 build findings (2026-11-25) | **Pinned versions:** `postgres:17.12-alpine`, `python:3.12.16-slim-bookworm`, `node:24.22.3-alpine`, `amir20/dozzle:v11.5.0`, Next 16.4.6, React 19.3, shadcn 4.23 (Radix base), FastAPI 0.165.0, SQLAlchemy 2.1.9, asyncpg 0.32.0, Alembic 1.20.1, uv 0.13.9. **Next 16:** `middleware.ts` is now `proxy.ts`; `next.config` is read at build time, so the API address is a build argument; Cache Components turned off to keep classic dynamic rendering. **Postgres host port 5433** by default, because a local Windows `postgresql-x64-17` service owns 5432 | Plan sections 3.1, 3.11, 3.15, 3.17 and 11 updated. Phase 0 exit criteria all verified |
| 33 | Phase 1 build finding (2026-11-25): how the rules treat events after "now" | **Rules evaluate as of `now`:** a To-Do or Issue created after now doesn't exist yet, and one done or solved after now isn't done or solved yet. At the seed's default APP_NOW (and any later date) this changes nothing; it keeps the rules report sensible if graders run it at an earlier date. Issue-order ties on identical `created_at` fall back to the Issue id, so the order is always deterministic | Goes in the README's assumptions. Implemented in `backend/app/rules/` |
| 34 | Phase 2 build findings (2026-11-25) | **"Ratings only until the meeting ends" is an API rule, not a trigger**, because the seeded meetings are ended and already rated. **CHECKs are written NULL-safe**: a NULL result passes a CHECK, which let "solved without a note" through until a test caught it. **One statement per `op.execute`** in migrations (asyncpg prepares each one). The `issues -> todos` foreign key is added after both tables exist (Alembic's `create_table` skips `use_alter` keys). Seeded meetings are stored ended, in `conclude`, with no section timer. A `*_test` guard stops DB tests from ever touching the demo database | `docs/DB_SCHEMA.md` updated. Phase 2 exit criteria verified on the stack |
| 35 | Phase 2 review findings (2026-11-25) | **Routes take the session as `DbSession` (`Depends(get_session, scope="function")`)**, because FastAPI's default dependency scope commits after the response is sent (a test pins the order: handler, commit, close, response). **The seed runs once per database** (skips when the seed company exists) instead of re-inserting missing rows, so deletes made in the app survive restarts. **DB rule names live in `app/constraints.py`**, and a test checks each exists, so the error mapper and the docs can't drift from the schema. Fixes to an applied migration go in a new revision (`0003`), never into `0002` | `docs/DB_SCHEMA.md`, `docs/API_CONTRACTS.md` (decimal format) updated |
| 36 | Phase 3 build choices (2026-11-26) | **A dedicated on-demand `rules-report` compose service** (profile `tools`) rather than `run api`, which has no seed mount. It depends only on `db` and has its own build section for the same image, so a fresh clone builds on demand, `--build` picks up code edits, and running it never migrates or reseeds the demo database. **`make rules-report` pins `APP_NOW` to the seed's now and replaces the committed file only on success** (temp file, then move). **JSON alone on stdout, logs on stderr**, so redirecting gives a clean file. **It refuses any database not named `*_report` or `*_test`**, because it wipes the one it uses. **`now` is always the frozen `APP_NOW`**, whatever `APP_CLOCK_MODE` says. **Meetings are recomputed, not read from snapshots, and listed only if ended as of `now`** (decision 33), so an earlier `APP_NOW` drops `mt2` | Commands documented in section 6 and `.env.example`. Phase 3 review (9 findings) fixed these seams: atomic and date-pinned regeneration, `--build`, no `migrate` dependency, the tests container mounts the repo root (a missing single-file bind mount becomes a host directory), the guard test points at a database that doesn't exist, plus a `make seed` target |
| 37 | Phase 4 build choices (2026-11-26) | **Session cookie signed with stdlib HMAC-SHA256** instead of `itsdangerous` (same construction, no new dependency); its 12 h age uses real time, through `clock.wall_clock()`, while every business value uses the injected `APP_NOW` clock. **Writes are guarded in one pure-ASGI middleware** (`ApiGuardMiddleware`: 413, 415, `csrf_failed`, security headers) inside the request logger, so refusals keep their request id. **The route-table test walks the OpenAPI operations**, because FastAPI 0.165 keeps included routers lazily (`app.routes` isn't flat). **Rate limits stay in layer L4** (they need Redis); meetings and SSE are Phase 5, but `GET /teams/{id}` already returns the meeting state object for an active meeting. **Unknown fields are refused, and `team_id` only ever comes from the path.** An unknown team is 403 for members and 404 only for Admins | `docs/API_CONTRACTS.md` status, ratings and `source_issue` shapes updated |
| 38 | Phase 4 review findings (2026-11-26) | **The shared clock anchor moves into Phase 4**: once the API writes rows stamped with business time, every process must agree on "now", across workers and restarts, or the as-of-now rules (decision 33) hide fresh writes. Business time therefore keeps counting from the first start; `docker compose down -v` or a new `APP_NOW` starts it over. **Logout revokes by epoch**: the signed cookie carries `users.session_epoch` and logout bumps it, which ends that user's sessions everywhere (simplest server-side revocation for a stateless cookie; acceptable for a seeded user switcher). **Make it an Issue looks for an open Issue before the window check.** **`WEB_ORIGIN` is a comma-separated list** defaulting to localhost and `PUBLIC_HOST` on `WEB_PORT` | `docs/DB_SCHEMA.md` (users, clock anchor), `docs/API_CONTRACTS.md` (status, logout) updated |
| 39 | Phase 5 build choices (2026-11-27) | **The LISTEN connection is a raw asyncpg connection** outside the SQLAlchemy pool (`eos-api:listen:<host>:<pid>`), pinged every 5 s and reconnected with backoff; after a reconnect every local stream resends `snapshot`. **A stream subscribes inside its generator, then reads the snapshot**, so no event falls in between and a client that drops before streaming leaves nothing behind; the request's DB session ends before streaming and each snapshot uses a short-lived one. **Facilitator and rater rules are access guards** (`MeetingFacilitator`, `MeetingRater`), checked before the body like every other guard; the service re-checks under the row lock. **SIGTERM is hooked** to end streams at once (Uvicorn otherwise waits the whole grace period before lifespan shutdown). **The 5-streams-per-user cap is per worker**; a stuck client's queue is dropped and replaced by a resync; an event over NOTIFY's 8000-byte limit degrades to a `team.changed` hint. **Join is idempotent and silent** the second time | `docs/API_CONTRACTS.md` sections 9 and 10 updated |
| 40 | Phase 5 review findings (2026-11-27) | **Logout ends open streams through `NOTIFY`** (`{"close_user": ...}` on the same channel), so it reaches the user's streams on every worker, in the logout's own transaction. **A stream drops events its snapshot already covers**, keeping ids monotonic. **The listener resyncs on every connect**, since streams can open before a late first connect. **Real-time health is reported, not enforced**: `/healthz` shows `realtime.listener` but stays 200, like a degraded cache | `docs/API_CONTRACTS.md` sections 3 and 11 updated |
| 41 | Phase 6 build choices (2026-11-27) | **Server Actions call `refresh()` (`next/cache`, new in Next 16)** after a successful write instead of `revalidatePath`: every page here is dynamic, so re-rendering the current route is exactly what's needed. **`meeting.state` reaches the timer through a window event** rather than a React context (the stream lives in the team layout, the timer deep in the meeting page); the timer shows whichever is newer, the event or the server render. **Basic web security headers ship now** (`next.config` `headers()`); the nonce CSP stays in layer L4. **`openapi.json` lives at the repo root** and is regenerated with `make openapi`; a backend test fails when it drifts. **New dependencies, pinned exactly and at least two weeks old:** `zod` 4.6.7, `server-only` 0.0.1, `openapi-fetch` 0.17.0, `openapi-typescript` 7.13.0, plus shadcn components | Plan 3.17 otherwise followed as written |
| 42 | Phase 6 review findings (2026-11-27) | **Next.js is the edge for client identity**: `edge-headers.cjs` (preloaded with `node -r`) overwrites `X-Forwarded-For` with the TCP peer and drops `X-Real-IP`, `Forwarded` and `X-Request-ID` before Next sees a request, so the API's trust in the `web` container (3.15) holds; layer L2's PM2 config must keep the preload in `node_args`. **The live stream reconnects itself** after an HTTP-level failure (the browser's EventSource gives up on those) with a 1 to 15 s backoff, and refreshes once it is live, which also sends a logged-out tab to `/login`. **Failed forms return what was typed**, so React's automatic form reset refills it | Dockerfile CMD, `next.config` unchanged |
| 43 | Phase 7 build choices (2026-11-28) | **E2E runs on its own stack, not the demo one**: `api-e2e` and `web-e2e` (built with `API_INTERNAL_URL=http://api-e2e:8000`) use `eos_test` with a frozen clock and a fresh seed per run, so `make test` never changes what you're clicking through. **The runner is Microsoft's Playwright image** (`v1.65.1-noble`, matching `@playwright/test` 1.65.1), so browsers never need installing on the host. **Tests run one at a time** (they share one team's data). **The SSR check reads the raw HTML** the Next server sends, rather than a JavaScript-disabled browser: streamed sections are in the HTML but revealed by React's inline script, so a no-JS browser would see the skeletons. Still to come with L1 and L2: rerunning E2E with two API workers and two web workers | Plan section 6 otherwise followed |
| 44 | Layers L1 and L2 build choices (2026-11-28) | **The cross-worker proof uses two real processes, not `--workers 2`:** the kernel decides which worker accepts a connection (on the stack, 29 of 30 health probes hit the same worker), so a test can't rely on the two browsers landing apart; two `uvicorn app.main:app` processes on two ports make it certain, and they start together so they also race for the clock anchor. Stdlib `http.client`, no new test dependency. **`/healthz` reports `worker` (the process id)**, since its pool and stream counts are per worker. **PM2 comes from a lockfile** (`frontend/pm2/`), not a bare `npm install -g`, so transitive versions are fixed. **The web runner is a switch** (`WEB_RUNNER=pm2` or `node`, checked by `start.sh`, which also checks `WEB_INSTANCES` because PM2 exits 0 on a config error). **`stream-shutdown.cjs` hangs up proxied live streams on `SIGTERM`/`SIGINT`**, so a stop or `pm2 reload` never waits on an open tab; normal requests still finish. **PM2's monitoring agent is off** (`pmx: false`). **The API reads `WEB_RUNNER` and `WEB_INSTANCES` only as plain strings, for the banner**, so a value only the web server understands (`WEB_INSTANCES=max`) can never stop the API from starting; `start.sh` is what validates them. **`make test-web`** runs the preload and config tests with Node built-ins only (no install) | Plan 3.11, 3.13, section 6. Reviewer-facing: README known limitations need nothing new; the decision record can cite the 11 s to 1.2 s stop |
| 45 | L1 and L2 review findings (2026-11-28) | **A startup preflight before `uvicorn --workers`** (`app/preflight.py`): Uvicorn's parent restarts any worker that exits, at once and with no limit, and never exits itself, so a startup failure has to be caught before it starts the workers. The preflight builds the app and runs the real `lifespan` startup and shutdown once (no second copy of the startup steps to keep in sync), with its info logs muted; about 1 s on a good start. Workers that die later are still restarted by the parent. **`stream-shutdown.cjs` exits itself on a stop signal while it is the only handler** (before Next listens), with Next's own codes, and **tracks responses, not sockets**. **Settings errors hide their input** (`hide_input_in_errors`), since the preflight logs them | Plan 3.11, 3.13. Reviewer-facing: the decision record can cite the restart-loop finding as a multi-worker trap |
| 46 | Layer L3 build choices (2026-11-28) | **Keys carry the database name** (`eos:{database}:{g}:...`), so the demo, test and E2E databases can share one Redis without sharing entries (their team versions overlap). **The generation is a random token, not a counter:** a generation lost with a Redis restart or evicted by LRU is replaced by a new random one, so entries from before can never come back; every seed run, the tests' reseed included, replaces it (no separate test Redis index to flush). **The session epoch is never cached:** access facts are, but a logged-out token must fail at once. **Entries can expire by business time** (`Until`), because Issues and To-Dos are "as of now". **Every cache path returns the same JSON shape**, so cache on, off, hit, miss and Redis down give byte-identical responses (tested). **Redis has a password**, since cached entries are served as is. **`redis:8.2.3-bookworm`**, Debian like the API image | Plan 3.14, section 6. Reviewer-facing: the decision record can cite 39 ms to 6 ms per Scorecard read and one computation for ten simultaneous misses |
| 47 | L3 review findings (2026-11-28) | **The API's source hash is part of every key** (`code_fingerprint`, 8 hex characters of SHA-256 over `app/**/*.py`, computed once at import): cheaper and surer than remembering to bump a schema version. **Stampede locks carry a random token** and are released with a compare-and-delete script. **Waiters read the entry and the lock together** (`MGET`) and compute at once when the lock is gone without an entry. **`note=False` for lookups that every request makes**, so the log line is about the request's own data. **`make test` runs the API tests a second time with the cache off** (about 80 s more) | Plan 3.14, section 6 |
| 48 | Layer L4 build choices (2026-11-28) | **The nonce CSP lives in `proxy.ts`** (Next 16's middleware), and the root layout calls `connection()`, so every page renders per request; `style-src` keeps `'unsafe-inline'` without a nonce (a nonce would cancel it, and Radix sets style attributes); no `upgrade-insecure-requests` (it would break plain-HTTP LAN access). **Rate limits are a router-wide dependency on `/api/v1`**, so they run before a route's own dependencies and an over-limit write costs no database work; the user comes from the session token's signature (no query), a request without a valid session is left to the 401. **Keys per database** (`eos:<database>:rl:...`), so the E2E stack never spends the demo's budget; the E2E stack and the test suite run with limits off (the browser tests sign in many times a minute from one address), the six rate-limit tests switch them on for their own app. **Hardening on every container from our images**, not only `api` and `web` (`migrate`, `info`, `rules-report`, the E2E ones too), through one YAML anchor. **zod jitless** instead of `'unsafe-eval'` | Plan 3.15, section 5. Reviewer-facing: README security notes list the audit results and the switches |
| 49 | L4 review findings (2026-11-28) | **Logout is exempt from rate limits:** it only takes access away, and the web app forgets the cookie whatever the API says, so a refusal must never be possible. **`/healthz` `redis` reflects every layer that uses Redis** (the cache's pool, else the rate limiter's). **`start.sh` validates `CSP_MODE`** (`nonce` or `off`). **Runtime files in the web image belong to root**, read by the `node` user. **`make audit`** runs `pip-audit` on the API's locked runtime packages and `npm audit --omit=dev` on the web app's and PM2's lockfiles | Plan 3.15. Reviewer-facing: README security notes can point at `make audit` |

---

## 2. Deliverables checklist (Part 3 of the brief)

Reply to the Altri email with links to all of these. **Every link must open without requesting access.**

- [ ] Public Git repo with README (max 2 pages): setup, test command, assumptions, known limitations, AI tools used and where
- [ ] Working app via `docker compose up` (stack starts with seed data loaded; seed script safe to rerun)
- [ ] Rules report: one documented command printing every computed value in 2.6 as JSON (format in seed README). Commit output as `rules_report.json`
- [ ] One-page decision record covering 2.8 (five decisions)
- [ ] Video, up to 7 min (Loom or unlisted YouTube): core journey with **two browsers in the same meeting** plus main decisions
- [ ] Tests from one command: rule tests, API tests, one two-browser Playwright test, a fixture and clock note, one failure artifact (e.g. Playwright trace)

---

## 3. Architecture decisions

### 3.1 Repo layout

```
altri-eos-task/
  docker-compose.yml          # db, redis, migrate (one-shot), api, web, logs (Dozzle), info (one-shot banner)
  .env.example                # ports and dev-only credentials, all with defaults
  compose.dev.yml             # opt-in hot reload (next dev, no PM2): docker compose -f docker-compose.yml -f compose.dev.yml up
  Makefile                    # up, down, reset, test, seed, rules-report, rules-report-at, lint (raw commands also in README)
  README.md                   # <= 2 pages
  rules_report.json           # committed output
  docs/DECISIONS.md           # 1-page decision record (2.8)
  docs/DB_SCHEMA.md           # Mermaid ER diagram + constraints, triggers, indexes
  docs/API_CONTRACTS.md       # endpoint contracts, error codes, SSE events, seed-based examples
  docs/SCALING.md             # bonus: 1,000 companies note
  seed/seed.json              # copied verbatim from the Drive folder
  db/init/                    # creates eos_test, eos_report and eos_activity databases and all roles
  artifacts/                  # committed Playwright failure trace
  backend/
    app/
      main.py  config.py  clock.py  db.py  cache.py  security.py  logging.py  banner.py  preflight.py
      envelope.py  jsonutil.py  # error body shape; JSON encoding of rule outputs
      rules/                  # PURE functions: weeks, status, completion, rocks, order, rating, summary
      models/  schemas/  routers/  services/  authz.py  realtime.py
      activity/               # bonus: outbox writer helper, worker loop, internal read API
      rules_report.py         # python -m app.rules_report
      seed.py                 # python -m app.seed [--reset]
    alembic/versions/
    alembic_activity/versions/  # bonus: eos_activity migrations
    tests/{rules,unit,db,api}/  helpers.py
  frontend/                   # Next.js App Router, standalone build, ecosystem.config.cjs and start.sh for pm2-runtime (layer L2), edge-headers.cjs and stream-shutdown.cjs preloads, proxy.ts (CSP nonce; Next 16 renamed middleware.ts to proxy.ts)
  e2e/                        # Playwright, two browser contexts
```

Do not name the dev file `docker-compose.override.yml`: Compose loads that automatically, so reviewers would get dev mode. The default compose runs production builds (`next build`, then `pm2-runtime` in cluster mode, see 3.11).

### 3.2 Time and clock (highest-risk area, get this right first)

- Company zone is `America/Chicago`. Use `zoneinfo`, **never a fixed UTC offset**. DST ends on Sunday 2026-11-01, so the week of 10-26 is 169 hours long, and the seed has records minutes from week boundaries on purpose.
- A week is Monday 00:00:00 to Sunday 23:59:59 company time, named by its Monday (`week_start`, a `date`). `week_of(ts_utc) -> date` and `week_bounds(week_start) -> (start_utc, end_utc)` are the only two functions that do tz math. Everything else calls them.
- Store all timestamps as `timestamptz` (UTC). Store `due_date` and `week_start` as plain `date`.
- Scores are `NUMERIC`, compared as `Decimal`. No floats (goals like 3.0 and scores like 4.1 must hit boundaries exactly).
- Rounding: explicit `Decimal.quantize(ROUND_HALF_UP)`. Python's `round()` is banker's rounding and gives 12 for 12.5 and 8.2 for 8.25. Both are seeded cases.
- **Clock:** a `Clock` service reads `APP_NOW` (default `2026-11-11T15:00:00Z`). Two modes:
  - `ticking` (default for `docker compose up`): `now = app_now + (wall clock - real_now)`, using the shared `clock_anchor` row, so the live meeting timer counts and every API worker agrees on the time (3.13). The first process to start inserts the anchor (`ON CONFLICT DO NOTHING`). If the stored `app_now` differs from the `APP_NOW` env value, the row is replaced, so changing `APP_NOW` takes effect on the next start.
  - `frozen` (tests, rules report): `now = APP_NOW` exactly.
  - Never call `datetime.now()` outside `clock.py` (a grep test enforces it).
  - Because the anchor lives in the database, restarting a worker mid-meeting does not reset the clock. With several workers the anchor is required, not optional: per-process clocks would make workers disagree about the timer.

### 3.3 Data model (Postgres, Alembic migrations)

Full Mermaid ER diagram (renders on GitHub), focused views, every constraint, trigger and index: **[docs/DB_SCHEMA.md](docs/DB_SCHEMA.md)**. That file is the detailed source; this table is the summary. Change both together.

| Table | Key columns and constraints |
|---|---|
| `companies`, `users`, `teams`, `memberships` | `users.role CHECK IN ('admin','team_member','observer')`; `memberships PK(user_id, team_id)`; `teams.cache_version bigint`, bumped in every team-scoped write transaction (3.14) |
| `measurables` | `goal_type CHECK`, `goal_value/goal_min/goal_max` with a CHECK per type (e.g. `between` needs min <= max); `UNIQUE(id, team_id)` |
| `scores` | `PK(measurable_id, week_start)`, `value NUMERIC`, `version int`, `CHECK (extract(isodow from week_start) = 1)` |
| `rocks`, `milestones` | `rocks.status IN ('on_track','off_track','complete')`, `quarter` text like `2026-Q4`; `UNIQUE(id, team_id)` |
| `issues` | `priority CHECK 1..5 or NULL`; `version int`; `source_kind IN ('measurable_week','rock','todo') or NULL` with matching nullable source columns (`source_measurable_id + source_week_start`, `source_rock_id`, `source_todo_id`) and a CHECK that exactly the columns for that kind are set; CHECK solved implies non-blank `resolution_note`; `UNIQUE(id, team_id)`; composite same-team FKs to each source |
| `todos` | `due_date date`, `done_at`, `source_issue_id` nullable; composite FK `(source_issue_id, team_id) -> issues(id, team_id)`; `UNIQUE(id, team_id)` |
| `meetings` | `section IN ('scorecard','ids','conclude')`, `section_started_at`, `facilitator_id`, `scorecard_week`, `ended_at`; **partial unique index** `(team_id) WHERE ended_at IS NULL` = one active meeting per team |
| `meeting_attendees` | `PK(meeting_id, user_id)`, `joined_at` |
| `meeting_ratings` | `PK(meeting_id, user_id)`, `rating CHECK 1..10`, FK to attendees |
| `meeting_summaries` | `meeting_id PK`, `summary jsonb`, `created_at` (frozen at meeting end, see 3.9) |
| `activity_outbox` (bonus) | `id bigserial`, `created_at`, `payload jsonb`: append-only hand-off to the activity worker, filled by a row trigger on every data table (3.18). The events themselves live in the separate `eos_activity` database |
| `clock_anchor` | One row (`id = 1`): `app_now`, `real_now`. Shared origin of the ticking clock for every API worker (3.2, 3.13) |

Only `measurable_week` sources are core. The Rock and To-Do source columns exist from the first migration so the bonus "Issue from Rock/To-Do" needs no schema rework, just endpoints and two more partial unique indexes.

How Issues and To-Dos link to sources (2.8 item 1): an Issue stores its source as real typed columns, not a text blob, so dedupe can be a unique index. A To-Do stores `source_issue_id`. All links are same-team enforced by composite FKs.

Role rules that FKs cannot express (Observers own nothing; facilitator and raters must be Admin or Team Member; owners must be Team-eligible per decision 5) get a trigger **and** an API check. The DB constraint is the safety net; the API check gives the clear error.

### 3.4 Rules module (single source of truth)

All of 2.6 lives as pure functions in `backend/app/rules/`, no DB, no clock reads (they take `now` and data in). The API, the rules report, the meeting snapshot and the tests all call the same functions, so nothing can drift.

`week_of`, `week_bounds`, `measurable_status`, `todo_completion`, `rock_status`, `rock_progress`, `issue_order`, `meeting_rating`, `round_half_up`, `build_meeting_summary`.

### 3.5 API (REST, `/api/v1`, OpenAPI at `/docs`)

Full contracts (request and response bodies, every error code, access level per endpoint, SSE event formats, seed-based examples): **[docs/API_CONTRACTS.md](docs/API_CONTRACTS.md)**. The table below is the summary.

| Area | Endpoints |
|---|---|
| Session | `GET /auth/users` (seed user switcher), `POST /auth/login {user_id}`, `POST /auth/logout`, `GET /me` (user, teams with a `can_write` hint, company time zone, and the server clock: now, today, current and last closed week) |
| Teams | `GET /teams` (accessible ones; all for Admin), `GET /teams/{id}` (members, eligible owners per decision 5, active meeting) |
| Scorecard | `GET /teams/{id}/scorecard`, `PUT /teams/{id}/measurables/{mid}/scores/{week_start}`, `DELETE` same path (clear a score), `POST /teams/{id}/measurables/{mid}/scores/{week_start}/issue` (Make it an Issue: `201` created or `200` existing) |
| Issues | `GET /teams/{id}/issues?status=unsolved\|solved`, `POST /teams/{id}/issues`, `PATCH /issues/{id}` (priority), `POST /issues/{id}/solve {note}`, `POST /issues/{id}/todos` |
| To-Dos | `GET /teams/{id}/todos`, `PUT /todos/{id}/done {done: bool}` |
| Rocks | `GET /teams/{id}/rocks` (read-only, with milestones, status, progress) |
| Meetings | `POST /teams/{id}/meetings` (start; `409` with the active meeting id if one exists), `GET /teams/{id}/meetings/active`, `GET /meetings/{id}`, `POST /meetings/{id}/join`, `POST /meetings/{id}/advance`, `POST /meetings/{id}/end`, `PUT /meetings/{id}/rating`, `GET /meetings/{id}/summary` |
| Live updates | `GET /teams/{id}/events` (SSE): team data changes and the team's meeting events in one stream (3.17) |

Conventions:

- Pydantic v2 validation: reject unknown fields, trim and length-limit strings, finite numbers only, `week_start` must be a Monday inside the 13-week window.
- One error envelope `{error: {code, message, details, request_id}}`. `401` not signed in, `403` signed in but no right, `404` unknown id, `409` conflict, `422` validation.
- `403` (not `404`) for an inaccessible team, documented as a trade-off (clear errors versus hiding existence).
- New To-Do from an Issue: `due_date = today in company time + 7 days`.
- Session (decision 4): `POST /auth/login` sets an HMAC-signed httpOnly cookie, seeded users only, no passwords. Next.js proxies `/api` to FastAPI, so cookies are same-origin and there is no CORS. Cookie attributes, CSRF protection, validation limits, headers and rate limits: 3.15.

### 3.6 Authorization (15% of the grade)

- One `authz.py` policy. Every route declares what it needs through a dependency: `require_team_read(team_id)` or `require_team_write(team_id)`. Resources fetched by id (issue, todo, meeting) resolve to their `team_id` first, then go through the same check, so guessed ids cannot cross team boundaries.
- Admin passes every team. Team Member passes only own teams. Observer passes read-only on own teams.
- **Route-table test:** iterate FastAPI's route list and assert every non-GET route returns `403` for an Observer, and every team-scoped route refuses a foreign Team Member. A new endpoint added later without a guard fails the suite.

### 3.7 Real-time meeting (2.8 item 3, decision 3: SSE + REST)

- **Source of truth is the database**, not process memory: `meetings.section`, `section_started_at`, `facilitator_id`, `ended_at`. Late join, refresh and reconnect (facilitator included) just reload state, so recovery needs no special code.
- **Transport:** Server-Sent Events for server-to-client, plain REST for commands. Reasons: browser auto-reconnect, works through proxies, commands reuse the tested authz path. Trade-off versus WebSocket: one-way only, which is fine because every client action is a REST call.
- On connect the stream sends a full `snapshot`, then small events: `meeting.state`, `team.changed {entity}` (clients call `router.refresh()` and the server re-renders, so Scorecard and Issues stay live inside the meeting; 3.17), `meeting.ended`. Heartbeat every ~15 s. Target latency well under 1 s.
- Fan-out: each API worker keeps an in-process hub (asyncio queues per team stream) and one dedicated `LISTEN` connection (3.12). Each write issues `NOTIFY eos_events, '<json>'` inside its transaction, so Postgres delivers it only on commit; every worker receives it and pushes it to its own SSE clients. Required, because the API runs several workers (3.13): the facilitator and a follower are often on different workers.
- **Server-owned timer:** the state payload carries `server_now`, `section_started_at`, `section_duration_s` (300 / 3600 / 600). Clients compute remaining time from the server offset. Past zero the UI shows **over time** (red, counting up). **Nothing auto-advances.**
- `advance`: facilitator only, forward only, compare-and-set (`UPDATE ... WHERE section = :expected`) so a double click cannot skip a section. `end`: facilitator only, any time, from any section.
- Start: Admin or Team Member only, becomes facilitator, partial unique index blocks a second active meeting. Join: anyone who can read the team (Observers included). Rating: attending Admin or Team Member, 1 to 10, upsert until `ended_at`.
- Meeting attribution: Issues solved and To-Dos created by the team between `started_at` and `ended_at` belong to the meeting. This matches how the seeded meetings must be computed (they have no explicit links). Documented as an assumption.

### 3.8 Make it an Issue without duplicates (2.8 item 4)

Enforce it in Postgres, not in app code:

```sql
CREATE UNIQUE INDEX ux_issues_open_measurable_week
  ON issues (source_measurable_id, source_week_start)
  WHERE solved_at IS NULL AND source_kind = 'measurable_week';
```

Handler order:

1. If an unsolved Issue already links to this Measurable and week, return it (`200`), even if the score has since changed.
2. Otherwise the cell must be off track right now, else `422` (the button only exists on off-track cells, but the server checks too).
3. `INSERT ... ON CONFLICT (source_measurable_id, source_week_start) WHERE solved_at IS NULL AND source_kind = 'measurable_week' DO NOTHING RETURNING *`. If no row comes back, a concurrent request won, so `SELECT` and return that one (`200`); else `201`.

Two simultaneous clicks serialize on the team row lock that every team write takes first (`bump_team`, 3.14): the later click finds the winner in step 1. The partial unique index is the backstop for any write path that skips that lock: the insert hits `ON CONFLICT`, and the loser reads the winner's row (tests force this path, plus a 20-way concurrent test). No select-then-insert race, no advisory locks. Solved Issues fall out of the index, so a fresh one can be created after solving (matches the seed's solved `i6`).

Title format follows the seed: `"<Measurable name>, week of <Mon D>"` (e.g. `New deals closed, week of Nov 2`). The clicker becomes owner.

### 3.9 Past meeting summaries stay unchanged (2.8 item 5, decision 11: implement)

- When a meeting ends, `build_meeting_summary` runs in the **same transaction** as setting `ended_at` and stores the result in `meeting_summaries`: statuses for the reviewed week, solved Issue ids, created To-Do ids, attendees, rating.
- The seed script writes snapshots for the two seeded meetings (`mt1`, `mt2`) by running the same function as of each meeting's `ended_at`.
- `GET /meetings/{id}/summary` serves only the snapshot and never recomputes. Later score edits or solved Issues cannot change a past summary.
- The rules report is the deliberate exception: it **recomputes from data**, because the graders run it at other dates. But it always wipes and reseeds its own scratch database (`eos_report`) first, so it reflects the pristine seed at `APP_NOW` and **never sees edits made in the app**. On that fresh seed, its meeting entries and the frozen snapshots are identical (a DB test checks this). Edits made in the app only ever change what the API shows. Document it.

### 3.10 Debug log viewer (decisions 8 to 10)

- **Viewer:** a Dozzle container in `docker-compose.yml`, always on, published as `127.0.0.1:8080:8080` so it is only reachable from the local machine. Pin an exact image tag. It shows the live logs of every container (api, web, db) with search and filtering.
- **Backend and frontend logs are separate streams (decision 20).** Dozzle shows one log stream per container, so `api` (FastAPI) and `web` (Next.js under PM2) never mix. Compose labels make them easy to find: `dev.dozzle.name` gives readable names (`backend (FastAPI)`, `frontend (Next.js / PM2)`), and `dev.dozzle.group` puts them in an `app` group, apart from an `infra` group (`db`, `redis`). The two can be opened side by side in Dozzle.
  - **Frontend (PM2):** run `pm2-runtime --json`, so every worker line is JSON: `{"message", "timestamp", "type", "process_id", "app_name"}`, where `type` is `out`, `err` or `process_event` (start, online, exit) and `process_id` is the PM2 worker (0, 1); confirmed in layer L2. PM2's own lines (`PM2 log: ...`) stay plain text. The app's own server logs (pino) add `worker` from `NODE_APP_INSTANCE`, which PM2 sets for each cluster worker. Worker 0 and worker 1 can then be filtered apart inside the `web` stream. Fully separate streams per PM2 worker would need one container per worker, which defeats cluster mode.
  - **Backend (Uvicorn):** the JSON request logs include `pid`, so the two Uvicorn workers filter the same way. Uvicorn's built-in access log is turned off to avoid duplicate lines.
  - **Optional, if time:** browser errors are posted to a small `web` route and logged there, so client-side crashes also land in the frontend stream.
- **API logging middleware** (`backend/app/logging.py`), one JSON line per request: `ts, level, request_id, method, path, query, user_id, status, duration_ms, request_body, response_body`.
  - Bodies are truncated at ~8 KB.
  - `cookie`, `set-cookie` and `authorization` headers and the session token are redacted.
  - SSE streams log open, close and each event type, not the stream body.
- **Errors:** unhandled exceptions log a `level=error` line with the traceback and `request_id`. The client gets a generic `500` with the same `request_id` and never sees a stack trace. The frontend shows the `request_id` in error toasts, so any failure can be found in Dozzle in seconds.
- Toggles: `LOG_PAYLOADS=true` (default per decision 10) and `LOG_LEVEL=debug`, so payload logging can be switched off with one env var.
- **Security note for the README:** Dozzle needs the Docker socket. Mounting it with `:ro` does **not** limit the Docker API, so Dozzle effectively has full control of the local Docker engine. That is acceptable for a local review stack bound to localhost, never for a shared or production host. Logging full payloads is likewise a dev-only choice. Saying this openly is better for the security score than leaving a reviewer to find it.
- This is not the activity log. Logs are transport-level and short-lived; the activity log (3.18, bonus) is durable, domain-level history in its own database.

### 3.11 `docker compose up` stack and startup banner (decision 13)

One command from a clean clone builds the images, starts everything, migrates, seeds, and prints where to go.

| Service | Image | Host port (default, override in `.env`) | Purpose | Ready when |
|---|---|---|---|---|
| `db` | `postgres` (pinned tag) | `127.0.0.1:5433` (`DB_PORT`) | Postgres, data in a named volume | `pg_isready` healthcheck |
| `redis` | `redis` (pinned tag) | `127.0.0.1:6379` (`REDIS_PORT`) | Cache only, no persistence, LRU at 128 MB (3.14) | `redis-cli ping` healthcheck |
| `migrate` | api image | none | One-shot: `alembic upgrade head`, then `python -m app.seed`, then exits `0` | `service_completed_successfully` |
| `api` | `backend/Dockerfile` | `8000` (`API_PORT`) | FastAPI run by **Uvicorn with `API_WORKERS` processes** (default 2, 3.13). API docs at `/docs` (Swagger UI) and `/redoc`, schema at `/openapi.json` | `GET /healthz` returns OK (also checks the DB pool) |
| `activity` (bonus) | api image | none (internal `8100` only) | Activity worker: drains the outbox into `eos_activity` and serves Admin activity reads to the API (3.18) | internal `/healthz` |
| `web` | `frontend/Dockerfile` | `3000` (`WEB_PORT`) | Next.js standalone production build run by **`pm2-runtime` in cluster mode** (`WEB_INSTANCES` workers, default 2), proxies `/api` to `api` | `GET /healthz` (a Next route handler; not under `/api`, which is proxied to FastAPI) via `wget` |
| `logs` | `amir20/dozzle` (pinned tag) | `127.0.0.1:8080` (`LOGS_PORT`) | Log viewer (3.10) | starts immediately |
| `info` | api image | none | One-shot banner: waits for `api` and `web` to be healthy, prints, exits `0` | n/a |

**Startup order** via `depends_on` conditions: `db` and `redis` healthy, then `migrate` completed, then `api` healthy, then `web` healthy, then `info` prints. A failed migration or seed keeps `api` from starting, so a broken stack fails loudly instead of half-working.

**Banner** (`python -m app.banner`): built from the database and the real port variables, so it cannot drift from the seed or from a changed port. Plain ASCII so it renders in Windows PowerShell 5.1 as well. Target output:

```
info-1  | ==============================================================
info-1  |  EOS L10 app is ready        APP_NOW 2026-11-11T15:00:00Z (ticking)
info-1  | --------------------------------------------------------------
info-1  |  App (Next.js)   http://localhost:3000    pm2 cluster x2
info-1  |  API (FastAPI)   http://localhost:8000    uvicorn x2
info-1  |  API docs        http://localhost:8000/docs    ReDoc: /redoc
info-1  |  Logs (Dozzle)   http://localhost:8080
info-1  |  Activity worker internal only, outbox backlog 0   (bonus)
info-1  |  Postgres        postgresql://eos:eos_dev_pw@localhost:5433/eos
info-1  |  Redis (cache)   redis://localhost:6379
info-1  | --------------------------------------------------------------
info-1  |  Sign in: open the app and pick a user (no passwords)
info-1  |  ID  Name          Email              Role         Teams
info-1  |  u1  Avery Admin   avery@acme.test    admin        all teams
info-1  |  u2  Blake Brooks  blake@acme.test    team_member  Leadership, Sales
info-1  |  u3  Casey Cho     casey@acme.test    team_member  Leadership
info-1  |  u4  Dana Diaz     dana@acme.test     team_member  Leadership, Operations
info-1  |  u5  Ellis Evans   ellis@acme.test    observer     Leadership
info-1  |  u6  Finley Ford   finley@acme.test   team_member  Sales
info-1  |  u7  Gray Green    gray@acme.test     observer     Sales
info-1  |  u8  Harper Hill   harper@acme.test   team_member  Operations
info-1  |  u9  Indy Ito      indy@acme.test     team_member  Operations
info-1  | --------------------------------------------------------------
info-1  |  Two-browser demo: u1 in one window, u3 in a private window
info-1  |  Show this again:  docker compose logs info
info-1  | ==============================================================
```

Notes:

- **"Login credentials":** sign-in has no passwords (decision 4), so the banner lists the seeded users to pick in the switcher, with email, role and teams. The Postgres user and password are dev-only defaults from `.env.example` (shown as `eos_dev_pw` above). No real secret is committed.
- **Seeding on every `up` is safe:** `migrate` runs the seed each time, but the seed does nothing once the database has the seed company (the whole seed is one transaction, so that row means "fully seeded"). Edits **and deletes** you make in the app survive restarts; re-inserting "missing" rows would bring a deleted score back. `docker compose down -v` gives a clean slate; the next `up` re-migrates and re-seeds.
- **Banner visibility:** attached `docker compose up` interleaves every service's logs. The banner appears once everything is healthy, but request logs keep scrolling after it. So also: `docker compose logs info` (or `make info`) any time, and `make up` = `docker compose up -d --build`, then `docker compose wait info` (the banner container only starts once api and web are healthy), then the banner on a clean screen. Not `up --wait`: it fails whenever the one-shot `info` container has already exited.
- **Requires Docker Engine 25+ / Docker Desktop 4.27+:** the healthchecks use `start_interval` (probe every 2 s while starting, every 30 s after), which older engines reject. Goes in the README prerequisites.
- **Less noise above the banner:** quiet log levels for `db` and `logs`, `NEXT_TELEMETRY_DISABLED=1` for `web`.
- **Port binding:** Postgres, Redis and Dozzle bind to 127.0.0.1 only. `web` and `api` also default to 127.0.0.1; `BIND_ADDR=0.0.0.0` in `.env` opens them to the LAN (for example to join a meeting from a phone).
- **Port clashes:** the host port for Postgres defaults to **5433**, not 5432, because a local Postgres often already owns 5432 (it does on the dev machine: a Windows `postgresql-x64-17` service). Any other clash: change the port in `.env`; the banner prints whatever is in use.
- **First run** builds the images and takes a few minutes; later runs start in seconds.
- **PM2 cluster mode for `web` (decision 14):**
  - **Built in layer L2 (v31, decision 44).** `frontend/ecosystem.config.cjs` (`.cjs` like the preloads, so it is CommonJS whatever the package type): `script` is Next's standalone `server.js`, `exec_mode: 'cluster'`, `instances` from `WEB_INSTANCES` (default 2, a positive whole number or `max`, anything else stops the start), `node_args` with the same two preloads as the plain runner (`edge-headers.cjs`, `stream-shutdown.cjs`), `autorestart` with `min_uptime`/`max_restarts` so a worker that crashes on start isn't restarted forever, `max_memory_restart: 512M`, `kill_timeout: 10000`, and `pmx: false` (no PM2 monitoring agent patching `http` in the workers). Workers share port 3000 through Node's cluster module. `HOSTNAME=0.0.0.0` inside the container.
  - `frontend/start.sh` is the container command: `WEB_RUNNER=pm2` (default) runs `pm2-runtime --json ecosystem.config.cjs`, `WEB_RUNNER=node` runs one plain `node` process (the layer switched off), anything else exits 64 with a message. Run with `pm2-runtime` (foreground, made for containers), **not** `pm2 start`, which daemonizes and would make the container exit at once. On `SIGTERM` it stops the workers (`SIGINT` each) and streams their logs to stdout, so Dozzle shows them.
  - PM2 7.1.2 is installed in the runtime image only, from its own lockfile (`frontend/pm2/`), so the image build is reproducible; `PM2_HOME=/tmp/.pm2`.
  - **Stopping never waits on an open tab (found while building L2):** on a stop signal Next closes its server and waits for open requests, and a proxied SSE stream never ends, so `docker compose stop web` with a meeting tab open took 11 s (PM2's `kill_timeout`, then `SIGKILL`; 25 s with the plain runner). `stream-shutdown.cjs` hangs up the live streams as soon as the signal arrives, like the API's own shutdown hook: the stop now takes 1.2 s, workers exit cleanly (code 130), and `EventSource` reconnects. It tracks the stream responses, not their sockets, so a normal request on a keep-alive connection whose stream already ended still finishes; and while it is the only handler for the signal (before Next is listening and installs its own), it exits itself with Next's codes (130, 143) instead of swallowing the stop (v32). Measured on the stack: `pm2 reload web` under steady traffic served 33 requests with 0 failures, and a worker killed with `kill -9` was back in 200 ms with no failed request.
  - Clustering is safe because `web` holds no state: sessions are the signed cookie, data comes from FastAPI, live updates come from FastAPI's SSE stream. The app uses no ISR or Next data cache, so per-worker in-memory caches cannot disagree.
  - Default 2 workers, not `max`: inside a container `max` means every host CPU thread (16 on the Ryzen 7 5800H), which is far too much memory for a review laptop.
  - Dev mode (`compose.dev.yml`) runs plain `next dev` without PM2, because cluster mode and hot reload don't mix.
  - Trade-off for the decision record: containers usually scale by adding replicas, so PM2 inside a container is a deliberate choice. It uses several cores in one container, restarts crashed workers without a container restart, and allows a zero-downtime `pm2 reload`.

### 3.12 Database connections: pooling, lifecycle, application names (decision 15)

SQLAlchemy 2.0 async engine on `asyncpg`, one engine per process.

**Pool settings** (env vars in `.env.example`, read by `config.py`):

| Setting | Default | Why |
|---|---|---|
| `DB_POOL_SIZE` | 5 | Steady connections per API worker |
| `DB_MAX_OVERFLOW` | 5 | Burst headroom per worker, closed again when idle |
| `DB_POOL_TIMEOUT` | 5 s | Wait for a free connection, then fail fast with `503 db_busy` instead of hanging the request |
| `DB_POOL_RECYCLE` | 1800 s | Replace old connections before any idle cutoff drops them |
| `pool_pre_ping` | on | Detects connections broken by a DB restart and replaces them transparently |
| `statement_timeout` | 5 s | A runaway query cannot hold a connection forever |
| `idle_in_transaction_session_timeout` | 10 s | A forgotten open transaction cannot block others or leak a connection |

The two timeouts and the application name are passed as asyncpg `server_settings`, so they apply to every connection the pool opens.

**Connection budget** (Postgres default `max_connections` = 100):

| Who | Connections |
|---|---|
| API pools: `API_WORKERS` x (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`) = 2 x 10 | up to 20 |
| API `LISTEN` connections, one per worker | 2 |
| Activity worker (bonus, 3.18): 2 to the main database, 3 to `eos_activity` | 5 |
| `migrate`, `info`, seed, rules report (short-lived, `NullPool`, one connection each) | 1 to 4 |
| Test suite (`NullPool`, against `eos_test`) | a few |
| **Total at defaults** | **under 30** |

At startup the API logs a warning if `API_WORKERS x (pool + overflow + 1)` exceeds 80% of the server's `max_connections`, so a scale-up that cannot fit shows up immediately instead of under load.

**Pool lifecycle** (`backend/app/db.py`, driven by FastAPI's `lifespan`):

1. **Create in `lifespan`, never at import time.** Each Uvicorn worker is a separate process and must own its own pool. Connections shared across a process boundary get corrupted.
2. **Wait for the DB:** `SELECT 1` with retry and backoff (about 30 s max). Compose healthchecks already order startup, but this also survives a DB restart or a slow first boot.
3. **Start the listener:** a dedicated `LISTEN` connection outside the pool, in a background task with a reconnect loop. After a reconnect it tells local SSE clients to refetch their snapshot, because notifications sent while it was down are lost.
4. **Per request:** a dependency yields an `AsyncSession`, commits on success, rolls back on error, and always returns the connection. Transactions stay short, with no outside network calls inside them. Routes take it as `DbSession` = `Depends(get_session, scope="function")`: FastAPI's default `"request"` scope runs the code after `yield` only after the response is sent, so the client would see a `2xx` before the commit, and a failed commit could never become a `500` (decision 35).
5. **SSE never pins a connection:** the stream reads its snapshot with a short-lived session, releases it, then waits on the in-process hub. Otherwise each open meeting tab would hold a connection and drain the pool.
6. **Readiness:** `GET /healthz` acquires a connection and runs `SELECT 1` within 1 s, and returns pool counters (`size`, `checked_out`, `overflow`). No hostnames or credentials in the response.
7. **Leak watch:** SQLAlchemy `checkout`/`checkin` pool events log a warning with the `request_id` when a connection stays checked out longer than 5 s. It shows up in Dozzle.
8. **Shutdown (`SIGTERM`):** Uvicorn stops accepting connections, then waits for open connections (bounded by `--timeout-graceful-shutdown`) before it runs the lifespan shutdown. SSE streams never finish on their own, so a hook on `SIGTERM`/`SIGINT` (`on_shutdown_signal`, wrapping Uvicorn's own handler) ends this worker's streams at once and the browsers' `EventSource` reconnects, to another worker if one is up; measured: streams end 1 s after `SIGTERM` instead of 21 s (decision 39). The lifespan shutdown then cancels the listener and `await engine.dispose()` closes every pooled connection.
9. **CLIs** (`migrate`, `seed`, `rules_report`, `banner`) build a `NullPool` engine (no pooling: each connection is opened when needed and closed after) and dispose it before exiting. Tests use `NullPool` too, named `eos-test`, so each test's event loop gets fresh connections.

**Application names** (Postgres `application_name`, max 63 characters), set on every connection:

| Component | `application_name` |
|---|---|
| API request pool | `eos-api:pool:<hostname>:<pid>` |
| API LISTEN connection | `eos-api:listen:<hostname>:<pid>` |
| Migrations | `eos-migrate` |
| Seed | `eos-seed` |
| Rules report | `eos-rules-report` |
| Startup banner | `eos-banner` |
| Activity worker, main database (bonus) | `eos-activity:outbox:<hostname>:<pid>` |
| Activity worker, activity database (bonus) | `eos-activity:store:<hostname>:<pid>` |
| Test suite | `eos-test` |
| API Redis pool (3.14) | `CLIENT SETNAME eos-api:cache:<hostname>:<pid>` (Redis's equivalent) |

What this buys: `SELECT application_name, state, count(*) FROM pg_stat_activity GROUP BY 1, 2` shows exactly which worker or tool holds connections. Setting Postgres `log_line_prefix` to include `%a` makes slow-query and error lines in the `db` logs (visible in Dozzle) name their source too.

### 3.13 Scaling the API (decision 16, confirmed)

**Decision: Uvicorn's built-in multi-process mode** inside the one `api` container:

```
python -m app.preflight && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${API_WORKERS:-2} --no-access-log --timeout-graceful-shutdown 20
```

It is the API's equivalent of PM2 cluster mode for `web`: one port, several processes, and the parent process restarts a worker that dies. FastAPI's deployment docs describe the same approach (`fastapi run --workers N` wraps it).

| Option | Verdict |
|---|---|
| **Uvicorn `--workers N`** | **Chosen.** One flag and one env var, no new services, works with compose as-is |
| Gunicorn + Uvicorn workers | Same result, older setup, one more dependency. Only worth it for Gunicorn-specific features we don't need |
| PM2 for the API | PM2 cluster mode only works for Node apps. Fork mode with several Python processes would fight over port 8000 |
| `docker compose up --scale api=3` | Real horizontal scaling, but replicas cannot share host port 8000, so it needs a load balancer (nginx or Traefik) in front. A good "next step" for the 1,000-companies note, too much for this deadline |

What several workers force (already folded into the plan):

- **Shared real-time fan-out:** Postgres `LISTEN/NOTIFY` is now required (3.7), not a cut item. Without it, a facilitator on worker A and a follower on worker B never see each other's changes.
- **Shared clock:** the ticking clock reads the `clock_anchor` row (3.2), so every worker shows the same timer.
- **No in-process state:** meeting state, sessions and dedupe already live in Postgres or the signed cookie, so any worker can serve any request. No sticky sessions needed.
- **Connection budget:** pools are per worker (3.12), so `API_WORKERS` multiplies connections.
- **Startup failures must stop the container (v32, decision 45):** Uvicorn's parent restarts any worker that exits, at once and forever, and never exits itself, so with `--workers 2` a worker that cannot start (bad settings, no database, missing tables) looped inside a running container. The image first runs `python -m app.preflight`: it builds the app and runs one worker's real startup and shutdown (`lifespan`: database, clock anchor, `LISTEN` connection) once, and exits 1 with the error if anything fails, so a bad start stops the container in about 2 s, as a single process does. Workers that die later are still replaced by the parent.
- **Proof (layer L1, done):** the stack, the API tests and the E2E run with `API_WORKERS=2`. The deterministic cross-worker test is `tests/api/test_processes.py`: it starts `uvicorn app.main:app` twice, as two OS processes started at the same moment, and over real HTTP shows that they anchor one business clock, that a follower streaming from one follows a meeting run on the other within 1 s, and that `SIGTERM` ends a process's open streams at once while the other keeps serving. On the stack, `/healthz` names the worker that answered, a worker killed with `kill -9` is replaced by Uvicorn in about 4 s, and `docker compose stop api` with 4 open streams takes 1.7 s.

### 3.14 Caching layer: Redis (decision 18)

Redis sits between the API and Postgres as a **cache-aside read layer**: the API checks Redis first; on a miss it queries Postgres, runs the rules module, and stores the result. Postgres stays the only source of truth. Redis may be empty, outdated or down and the app stays correct, because every team-scoped cache key carries a version read from Postgres.

**Scope (decision 21):** everything in this section is core, built in its safe form: versions stamped in Postgres (below) and the stampede guard included.

**Why caching pays off here:** the expensive reads are computed read models (Scorecard grid with 13 weeks of statuses, ordered Issues, To-Dos with overdue flags and completion rate, Rocks with status). During a meeting every change sends an SSE event, and every attendee's page re-renders the same sections on the server at the same moment (3.17). With N attendees, each change costs N identical queries and rule runs; with the cache it costs one.

**Cacheable items** (all keys prefixed `eos:{database}:{code}:{g}:`, where `database` is the Postgres database name, `code` a short hash of the API's source (a changed build never reads an older build's entries) and `g` that database's generation, a random token; v33, v34):

| Item | Key | TTL | Invalidated by | Notes |
|---|---|---|---|---|
| Access facts per user (role, team ids) | `user:{uid}:access` | 300 s | Seed bumps `g` | Read by authz on every request. The session epoch is never cached: it is read from Postgres on every request, so a logout ends a session at once (v33). Facts only, never decisions; the policy still runs in code |
| Seeded user list (login switcher) | `ref:users` | 1 h | Seed bumps `g` | Users and teams can't be edited in the app (out of scope in the brief) |
| Team reference data: team, members, eligible owners, Measurable definitions | `team:{tid}:ref` | 1 h | Seed bumps `g` | All seeded, read-only in the app |
| Scorecard grid (13 weeks with statuses) | `team:{tid}:v{ver}:scorecard:{current_week}` | 600 s | Team version (Postgres) | Key holds the current week, so `pending` correctly becomes `off_track` once a week closes |
| Issues: unsolved (in Issue order) and solved | `team:{tid}:v{ver}:issues:{status}` | 600 s | Team version (Postgres) | |
| To-Dos with overdue flags and last closed week's rate | `team:{tid}:v{ver}:todos:{today}` | 600 s | Team version (Postgres) | Key holds today's company date, since overdue depends on it |
| Rocks with computed status and progress | `team:{tid}:rocks:{today}` | 1 h | Seed bumps `g` | Rocks are read-only; status only changes with the date |
| Active meeting state (section, facilitator, attendees, ratings) | `team:{tid}:v{ver}:meeting:{mid}` | 600 s | Team version (Postgres) | The timer's remaining time is computed per response from `section_started_at` and now, never cached |
| Ended meeting summaries | `summary:{mid}` | 24 h | Never: immutable by design (3.9) | The ideal cache entry |

**Never cached:**

- **The rules report.** It computes from a freshly seeded scratch database every time (Phase 3).
- **Writes and their guards.** Make it an Issue dedupe stays on the Postgres partial unique index (3.8). Lost-update `If-Match` checks compare against the database row. Redis locks are never used for correctness.
- **Authorization decisions.** Only per-user facts are cached. The check runs on every request **before** any cache lookup, so one team's cached data can never reach another team's user.
- **Clock and timer values.**

**Invalidation with version stamps in Postgres (the safe form).** Each team row has `cache_version bigint`. Every team-scoped write (scores, Issues, To-Dos, meeting actions) runs `UPDATE teams SET cache_version = cache_version + 1 WHERE id = :tid` **in the same transaction** as the change, and issues its `NOTIFY` in that transaction too. Readers first read the version with one primary-key lookup, then use the Redis key containing it. Why this is safe:

- The version and the data commit together. A reader racing a writer can at worst cache old data under the old version, which nobody reads after the commit. No deletes, no key scans.
- Redis cannot cause stale reads: an outdated entry can only sit under an old version, and the current version always comes from Postgres. If Redis loses data or goes down, reads simply miss.
- The cost is one tiny indexed query per cached read. What gets skipped is the expensive part: several queries plus the rules module.
- Postgres delivers `NOTIFY` only at commit, when the new version is already visible, so attendees who refetch on the event always get fresh data, across browsers and workers.
- Old entries are never read again and expire through their TTL.
- Coarse on purpose: any write in a team invalidates all of that team's read models. Writes are rare next to reads (a meeting makes tens of writes an hour), and one counter is far easier to prove correct than one per section.
- **Lock order (one hot row per team):** the bump locks the team's row until commit, so writes within one team queue behind each other. That is fine at this scale (short transactions, tens of writes an hour). To rule out deadlocks, the bump is always the **first** statement of every team-scoped write transaction, so every transaction takes the team lock before any other row lock. Writes in different teams never wait on each other. The bump is built in Phase 4, before the cache exists, so the write path never changes later.
- **Every seed run replaces the generation (v33):** `python -m app.seed` (the demo seed run by `migrate`, and the E2E stack's `e2e-seed`) writes a new random token to `eos:{database}:gen` after its transaction commits, which orphans every reference entry for that database. With the cache on, if it cannot reach Redis it exits 1, so `api` never starts on top of reference data cached before the seed (with the cache off it tries anyway, so switching it back on cannot find old entries). The test suite's reseed does the same; the rules report calls the loader directly and never touches Redis. A random token instead of a counter means a generation lost with a Redis restart or evicted by LRU is replaced by a new random one, so old entries can never come back. Reference data cannot change any other way, because users, teams, memberships, Measurables and Rocks have no edit endpoints.

**Failure behavior (Redis is optional at runtime):**

- Every Redis call has a short timeout (~50 ms). Errors fall back to Postgres and log a warning; after repeated failures a per-worker breaker skips Redis for 30 s.
- Redis trouble can only make reads slower, never stale, because versions come from Postgres. TTLs exist for memory hygiene, not for correctness.
- `/healthz` reports Redis as `ok` or `degraded` but stays healthy, because the app works without it.
- Sessions stay in the signed cookie and real-time stays on Postgres `NOTIFY`. Keeping Redis out of those paths is what lets it fail safely.

**Why not Redis pub/sub for real-time:** once Redis exists that is the usual choice, and it scales past `NOTIFY`'s limits (8000-byte payloads, all fan-out through the one Postgres primary). Staying on `NOTIFY` keeps real-time independent of a service we allow to fail. Redis pub/sub goes into `docs/SCALING.md` as the upgrade path.

**Client lifecycle** (same pattern as 3.12): one `redis.asyncio` connection pool per worker, created in `lifespan` and closed on shutdown, `max_connections` 20 per worker. Every connection is named with `CLIENT SETNAME eos-api:cache:<hostname>:<pid>`, so `CLIENT LIST` shows who is connected, like Postgres `application_name`. The code lives in `backend/app/cache.py` (`get_or_set`, version helpers, breaker), called by the service layer; routers don't change.

**Stampede guard (core, decision 21):** on a miss the first request takes a short lock (`SET ... NX PX 2000`) and computes; the others wait up to ~1 s for the entry, then compute themselves. Without it the worst case is N duplicate computations on one miss, which is slower but still correct.

**Observability:** each request log line gets `cache: hit | miss | bypass`, and `/healthz` returns hit and miss counters. Both show in Dozzle.

**Settings:** `REDIS_URL` (with the password), `REDIS_PASSWORD`, `CACHE_ENABLED=true`, `CACHE_TTL_TEAM=600`, `CACHE_TTL_REF=3600`. `CACHE_ENABLED=false` turns the whole layer off without code changes.

**Compose service:** `redis` (`redis:8.2.3-bookworm`, Debian like the API image) on `127.0.0.1:6379` (`REDIS_PORT`), configured as a pure cache: no persistence (`--save ''`, `--appendonly no`), `--maxmemory 128mb`, `--maxmemory-policy allkeys-lru`, `--requirepass` (dev default `redis_dev_pw`: a cached entry is served to users as is, so only the app may write one), healthcheck `redis-cli ping` with the password. `migrate` (and `e2e-seed`, and the `tests` runner) wait for it at startup; at runtime the app tolerates it disappearing.

**Trade-off to state in the decision record:** at the brief's data size Postgres alone is fast enough. The cache is there for meeting fan-out bursts and to show the pattern, and every correctness-critical path (dedupe, authz, rules report, real-time) bypasses it on purpose.

**Built in layer L3 (v33, decision 46):**

- `backend/app/cache.py`: `Cache` (per worker: Redis pool, breaker, hit and miss counters), `RequestCache` (per request: the generation is read once, and the outcome of the data lookups goes into the request log line), `get_or_set` with the stampede guard (owner-only lock release; waiters give up as soon as the computing request fails), `Until`, `rotate_generation`, `code_fingerprint`. Services take an optional cache; only read routes pass one (the `ReadCache` dependency), so writes and the reads inside them never touch it.
- Keys as listed, plus `team:{tid}:v{ver}:meeting:active` (the active meeting's state, or none) next to `meeting:{mid}`. Every cached read first reads the team's `cache_version` and company time zone in one primary-key lookup (`team_state`), then builds its key.
- **Time:** Issues and To-Dos are "as of now" to the instant (a row created, solved or done after now is not shown yet), so their entries record the next such timestamp after now (`Until`) and count as a miss once now reaches it. Only seed data can be timestamped in the future (a reviewer's earlier `APP_NOW`), but the entry is right in both clock modes either way.
- **Shape:** every path (hit, miss, Redis down, cache off) returns the same plain JSON values, which the response models parse back, and a test compares the raw response bytes of every cached endpoint with the cache off, on a miss and on a hit. `server_now` is added per response.
- **Tests:** the whole suite runs with the cache on (435 tests after the review), and `make test` reruns the API tests with `CACHE_ENABLED=false` (`make test-backend-uncached`: 168, the 15 cache tests skip); `tests/api/test_cache.py` covers hits, a write making entries unreachable, logout with cached access facts, seed orphaning, entries from future rows expiring, Redis down (same bytes, `degraded`, breaker), the seed refusing to finish without Redis, one computation for ten concurrent misses, and a failing computation releasing its lock.
- **Measured on the stack:** a Scorecard read went from 39 ms (miss) to 6 ms (hit); ten simultaneous reads of a cold entry computed it once (1 miss, 9 hits); the E2E run served 216 cached reads against 41 misses; with Redis stopped every read returned the same bytes (70 ms while the first calls timed out, 17 ms once the breaker opened) and `/healthz` said `degraded` with HTTP 200; after Redis came back the cache resumed within the 30 s breaker window.

### 3.15 Security hardening (decision 23)

The brief grades "roles and team boundaries enforced on the server and proven by tests, with inputs validated at the API" (15%). Authorization itself is 3.6; this section covers everything around it.

**Threat model:** a reviewer's browser on localhost; other web pages, including other localhost ports, trying to act through that browser; malformed or hostile API input; a bug in our own SQL. **Deliberately not covered:** the seeded user switcher lets anyone who can reach the app sign in as any seeded user. The brief allows this; the README says so, along with what production would use instead.

**Session cookie** `eos_session`:

- HMAC-signed payload `{uid, iat}` (HMAC-SHA256 with the stdlib `hmac` module rather than `itsdangerous`: same construction, one dependency fewer; decision 37). `HttpOnly`, `SameSite=Lax`, `Path=/`, 12 h max age checked on the server. `Secure` when `COOKIE_SECURE=true` (off for `http://localhost`).
- Unknown, expired or tampered cookie gives `401`. The token also carries the user's `session_epoch`; logout bumps it, so logging out ends every session of that user, in every browser, and a copied cookie stops working at once (decision 38). Login accepts only seeded user ids and returns a generic `401` otherwise.
- Signing key `SESSION_SECRET` from env. `.env.example` holds a dev value, and the API refuses to start with it when `APP_ENV=production`.

**CSRF protection (the gap found in review).** A cookie session lets another page make the browser send writes. Every `POST`/`PUT`/`PATCH`/`DELETE` passes three layers:

1. **`SameSite=Lax`:** browsers don't attach the cookie to cross-site writes. It does **not** cover other ports on localhost, because they count as the same site. Hence layers 2 and 3.
2. **Required custom header** `X-EOS-CSRF: 1`, added by the Next.js server's API client (every write is a Server Action calling FastAPI server-to-server, 3.17). A cross-origin page can't send a custom header without a CORS preflight, and the API never approves one for foreign origins.
3. **`Origin` check:** when present it must equal `WEB_ORIGIN` (`http://localhost:3000`), else `403`. Non-browser clients (tests, curl) send no `Origin` and rely on layer 2.

Writes must also be `Content-Type: application/json` (`415` otherwise), which a plain HTML form cannot send.

**CORS:** none by default, since the browser only talks to the Next.js origin, which proxies `/api`. If the SSE fallback from section 8 is ever used, allow exactly `WEB_ORIGIN` with credentials, never `*`.

**Input validation and mass assignment:**

- Pydantic request models with `extra="forbid"`: unknown fields give `422`. Input and output models are separate, so clients can never set `id`, `created_at`, `solved_at`, `version` or `cache_version`.
- `team_id` comes only from the URL path, never from the body. Owners must be eligible (decision 5).
- Strings are trimmed, non-blank where required, and length-capped (titles 200, notes 2000).
- Ids must match `^[a-z0-9_]{1,64}$` before any query runs.
- Scores: finite decimals, at most 4 decimal places, absolute value up to 1e9 (`NUMERIC(14,4)` plus a CHECK in the DB). Dates are ISO; weeks are Mondays inside the 13-week window. Priority 1 to 5, rating 1 to 10, also enforced by DB CHECKs.
- Request bodies over 64 KB give `413`.

**Output and XSS:** React escapes all text, and `dangerouslySetInnerHTML` is banned by lint (`react/no-danger`). User text (titles, notes) is only ever rendered as text.

**Security headers:**

| Where | Headers |
|---|---|
| `web` | `Content-Security-Policy` with a per-request nonce set in the Next.js `proxy.ts` (formerly middleware): `default-src 'self'; script-src 'self' 'nonce-<n>' 'strict-dynamic'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'` |
| `web` | `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, `Permissions-Policy: camera=(), microphone=(), geolocation=()` |
| `api` | `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on authenticated responses |

Notes: `style-src 'unsafe-inline'` is needed for the inline style attributes that Radix/shadcn components set. A nonce CSP makes every page render dynamically, which is fine for this app. `next dev` needs `'unsafe-eval'`, so the dev compose file relaxes CSP. No HSTS on plain-HTTP localhost; documented for production. If the nonce CSP fights the build, fall back to `script-src 'self' 'unsafe-inline'` and list it as a known limitation.

**Rate limiting** (Redis fixed window; if Redis is down it fails open and logs a warning):

| What | Limit |
|---|---|
| `POST /auth/login` | 10 per minute per IP |
| Make it an Issue | 30 per minute per user |
| Other writes | 120 per minute per user |
| Open SSE streams | 5 per user |

Over the limit gives `429` with `Retry-After`. Logins reach FastAPI from the Next.js server, so "per IP" must use the client address resolved by the request middleware: the last `X-Forwarded-For` entry, believed only when the peer is the `web` container (`TRUSTED_PROXY_HOSTS`). The middleware puts it in `request.state.client_ip`; the limiter keys on that, never on `request.client`, which is the web container for every proxied call. The test suite sets `RATE_LIMIT_ENABLED=false` except in the rate-limit tests, so normal tests never trip it.

**Data layer:**

- All SQL goes through SQLAlchemy bound parameters; no SQL built from strings. Real-time notifications use `SELECT pg_notify(:channel, :payload)`, because the `NOTIFY` statement itself cannot take bound parameters.
- **Least-privilege Postgres roles**, created by `db/init/`:
  - `eos_owner` owns the schema and runs migrations, the seed and the rules report.
  - `eos_app` is the API's login: only `SELECT`/`INSERT`/`UPDATE`/`DELETE` on app tables and sequence usage. No DDL, no `TRUNCATE`.
  - `eos_readonly` is the banner's login: `SELECT` only.
  - Effect: even an SQL injection bug in the API could not drop or truncate tables.
  - Activity log (bonus, 3.18): `eos_app` has no outbox privileges at all (triggers write it as `SECURITY DEFINER`) and may only execute `log_app_event()`; `eos_activity_consumer` gets `SELECT`/`DELETE` on the outbox plus `SELECT` on reference tables; `eos_activity_writer` only `INSERT`/`SELECT` on `activity_events` in `eos_activity`, which makes the log append-only.

**Real-time:** the SSE subscription is authorized at connect with the same team-read check as REST. Events carry ids and entity types, except `meeting.state`, which carries the meeting state object (`docs/API_CONTRACTS.md`). Every receiver is an authorized reader of that team, so an event never contains anything its receiver couldn't fetch through REST anyway. Payloads stay well under `NOTIFY`'s 8000-byte limit.

**Errors and logs:** generic `500` with a `request_id`, never a stack trace; FastAPI debug off; cookies, auth headers and the session token redacted in logs (3.10); JSON logging escapes newlines, so user text cannot forge log lines.

**Containers:**

- `api` and `web` run as a non-root user, with `no-new-privileges` and all Linux capabilities dropped. Built in layer L4 for every container from our images (`migrate`, `info`, `rules-report` and the E2E services too), through one YAML anchor (`x-hardening`).
- Read-only root filesystem with a 64 MB `tmpfs` for `/tmp` (where `PM2_HOME` is): built in layer L4 and works cleanly for all of them (`READ_ONLY_FS=false` turns it off). Verified: writes to `/app` fail with "Read-only file system", the processes' capability sets are all zero, and nothing in the logs failed to write.
- Postgres, Redis and Dozzle keep their official images' defaults.
- `.dockerignore` keeps `.env`, `.git` and `node_modules` out of images.

**Supply chain:** lockfiles committed (`uv.lock`, `package-lock.json`), image tags pinned, `pip-audit` and `npm audit --omit=dev` run once before submitting, with results noted in the README.

**README "Security notes" (documented, not fixed):**

| Accepted for this review stack | Production would use |
|---|---|
| User switcher, no passwords | OIDC / SSO login |
| Public `/docs` and `/auth/users` | Docs behind auth; no user listing |
| Always-on payload logging; Dozzle with Docker socket access (3.10) | Payload logging off; centralized logging without socket access |
| Plain HTTP on localhost | TLS with HSTS, `Secure` cookies |

### 3.16 Next.js to FastAPI: gzip and signed messages (decision 24)

**Scope:** gzip is core (about 15 minutes). HMAC request and response signing is **bonus rank 5**: fully designed here, built only once the core is green, otherwise described in the decision record.

```
Browser --(session cookie + CSRF header, 3.15)--> Next.js server --(HMAC-signed request)--> FastAPI
Browser <--(gzip)-- Next.js verifies signature <--(HMAC-signed, gzipped response)-- FastAPI
```

**Gzip (core):**

- Browser and Next.js: Next's production server gzips responses by default (`compress: true`); keep it on.
- FastAPI: Starlette `GZipMiddleware` with `minimum_size=1024`. `text/event-stream` is explicitly excluded so SSE events are never held back in a compression buffer. When building layer L5, check whether the installed Starlette version already skips SSE; exclude it explicitly either way.
- Request bodies are small JSON (64 KB cap), so they are not compressed in the core. With the signing bonus, the Next proxy gzips request bodies over 1 KB and FastAPI decompresses them with a 64 KB decompressed-size cap, which blocks zip bombs.

**HMAC signing (bonus rank 5), Next.js server to FastAPI only:**

- **Why this hop:** the secret lives in env on the `web` and `api` containers and never reaches the browser. A secret in browser JavaScript can be read in devtools, so it would only be obscurity. The browser hop is protected by the session cookie and CSRF layers instead (3.15).
- **Where signing happens:** in the shared server-side client `lib/api/server.ts` (3.17), which every Server Component and Server Action already uses, so all of their calls are signed and all responses verified in one place. The browser-facing `/api` proxy (SSE stream, direct API calls) switches from a `rewrites` rule to a route handler (`frontend/app/api/[...path]/route.ts`) that uses the same client. Side benefit: that handler controls SSE streaming itself, which removes the proxy-timeout risk in section 8.
- **Keys:** env `API_SIGNING_SECRET` (at least 32 random bytes) and `API_SIGNING_SALT`, identical in `web` and `api`, with a key id `API_SIGNING_KID`. At boot each process derives two keys with HKDF-SHA256: one for requests (Next to API) and one for responses (API to Next). A captured request signature can therefore never pass as a response signature.
- **Boot-time key cache (your LRU requirement):** derived keys are computed once at startup and held in an in-memory LRU keyed by key id (`functools.lru_cache(maxsize=8)` in Python, a small `Map`-based LRU in Node). No request ever re-derives a key. Rotation works by adding the new key id next to the old one. A process refuses to start if the secret is missing or shorter than 32 bytes. Secrets and derived keys are never logged.
- **What is signed (request):** `v1`, method, path with sorted query, timestamp, nonce, and the SHA-256 of the uncompressed body, joined by newlines. Headers: `X-EOS-Key-Id`, `X-EOS-Timestamp`, `X-EOS-Nonce` (128 random bits), `X-EOS-Signature` (HMAC-SHA256, base64url).
- **What is signed (response):** `v1`, status, the **request's** nonce, timestamp, and the SHA-256 of the body. Binding the response to the request nonce stops a valid response from being swapped onto another request.
- **FastAPI verification**, as middleware before routing:
  - Constant-time compare (`hmac.compare_digest`).
  - Timestamp within ±60 s of the **real wall clock**, not `APP_NOW`, which is business time and starts in 2026-11-11.
  - Nonce single-use: Redis `SET NX EX 120`. If Redis is down, a per-worker LRU of recent nonces (bounded at about 10,000) is used and a warning is logged, since it can't catch a replay sent to a different worker.
  - Any failure gives `401 signature_invalid` with no hint about which part failed.
- **Next.js verification:** the server-side client checks every response signature before a Server Component, Server Action or the proxy uses the data. A mismatch becomes a `502` (an inline error card on the page, or the proxy's response) and logs an error.
- **SSE:** a stream can't carry one signature up front, so each event carries its own `sig` over the request nonce, event id and SHA-256 of the event data. The proxy verifies every event before forwarding it.
- **Exempt routes:** `/healthz`, `/docs`, `/redoc`, `/openapi.json` (read-only, no user data).
- **Direct API access:** unsigned calls to `:8000` get `401`. The README shows two ways in: through `http://localhost:3000/api/v1/...` (the Next proxy signs it; needs the session cookie), or `make api ARGS="GET /api/v1/teams"`, a small script that signs with the env secret. Swagger's "Try it out" on `:8000` won't work, and that is documented.
- **Tests:** a test helper signs requests. Cases: missing signature, wrong key, tampered body, timestamp skew, replayed nonce (all `401`), and a tampered response rejected by the proxy (`502`). Python generates shared test vectors (`shared/signing_vectors.json`) that both the Python and the TypeScript test suites check, so both sides provably compute identical signatures.
- **For the decision record, what it does and doesn't buy:** it proves every API request came from our Next.js server unaltered and that responses came back unaltered, and it shuts out anything that can reach `:8000` without the secret. It does **not** hide payloads (that needs encryption or TLS/mTLS), and it does **not** replace user authentication: the cookie session and authorization are still checked on every request.

### 3.17 Frontend architecture: server-first rendering (decisions 25 and 26)

**Principle:** React Server Components by default. A component becomes a client component (`'use client'`) only when it needs something only a browser has: event handlers, local state, effects, timers, `EventSource`. Client components still arrive as server-rendered HTML on first load and hydrate afterwards, so every page is fully rendered before any JavaScript runs.

```mermaid
flowchart LR
    subgraph Browser
        HTML["Server-rendered HTML<br/>streamed per section"]
        CC["Client islands<br/>score cells, forms, dialogs, timer, controls"]
        RT["LiveRefresher<br/>one EventSource per team"]
    end
    subgraph NextJS ["Next.js server, PM2 cluster"]
        MW["proxy.ts<br/>CSP nonce, session cookie check"]
        RSC["Server Components<br/>fetch data, render sections"]
        SA["Server Actions<br/>every write"]
        PX["api proxy<br/>SSE and direct API calls"]
    end
    API["FastAPI, Uvicorn workers"]
    RSC -->|"typed client, forwards cookie"| API
    SA -->|"typed client, forwards cookie"| API
    RSC --> HTML
    CC -->|"form submit, useOptimistic"| SA
    SA -->|"revalidatePath"| RSC
    API -->|"SSE team.changed, meeting.state"| PX
    PX -->|SSE| RT
    RT -->|"router.refresh, debounced"| RSC
```

**What renders where:**

| Server Components (no JavaScript shipped) | Client components (only where required) |
|---|---|
| Page shells, header, team list, user menu content | `TeamSwitcher` dropdown, `UserMenu` toggle |
| Scorecard grid, statuses, week headers | `ScoreCell` (inline edit, optimistic), `MakeIssueButton` |
| Issue lists, solved list, source labels | `NewIssueForm`, `SolveIssueDialog`, `AddTodoDialog`, `PrioritySelect` |
| To-Do list, overdue flags, completion rate | `TodoDoneToggle` (optimistic) |
| Rocks with expandable Milestones (native `<details>`, no JavaScript) | none |
| Meeting agenda, attendee list, Conclude's new To-Dos, whole summary page | `SectionTimer`, `FacilitatorControls`, `RatingPicker`, `JoinOnMount` |
| Login user list | `LoginButton` per user (a plain form, works before hydration) |
| | `LiveRefresher` (SSE), `LiveIndicator`, toasts |

**Routes:**

| Route | Rendering | Purpose |
|---|---|---|
| `/login` | Server, one small client form per user | Seeded user switcher: cards grouped by role, showing each user's teams |
| `/` | Server | Redirects to the user's first accessible team |
| `/teams/[teamId]` | Server, sections streamed in `<Suspense>` | Team page: Scorecard, Issues (unsolved and solved tabs), To-Dos, Rocks |
| `/teams/[teamId]/meeting` | Server, with client timer and controls | Start, join, or run the team's active meeting |
| `/meetings/[meetingId]/summary` | Server only | Summary of any ended meeting, including seeded `mt1` and `mt2` |
| `/admin/activity` (bonus) | Server only | Admin-only activity log with git-style diffs (3.18) |
| `/healthz` | Route handler | Container healthcheck (3.11) |
| `/api/*` | `next.config` rewrite (core) or route handler (signing bonus, 3.16) | Proxy to FastAPI, used for the SSE stream and for direct API calls |

**Auth gate (server):** `proxy.ts` (Next 16's name for middleware) sets the CSP nonce and redirects to `/login` when there is no session cookie at all. The `(app)` layout fetches `/me`; `401` redirects to `/login`. The `teams/[teamId]` layout fetches the team: `403` renders a "You don't have access to this team" page, `404` calls `notFound()`. Guessed team URLs fail in the UI exactly as they do in the API.

**Reading data (server):**

- `lib/api/server.ts` imports `server-only`, so it can never end up in a browser bundle. It is the typed `openapi-fetch` client for `API_INTERNAL_URL`, and on every call it forwards the browser's session cookie, the client IP (`X-Forwarded-For`), a propagated `X-Request-ID` (one id across the `web` and `api` streams in Dozzle) and the `X-EOS-CSRF` header. Calls are wrapped in React `cache()`, so one render never fetches the same endpoint twice (for example `/me` from both layout and page).
- Pages are dynamic anyway (cookies and the CSP nonce), and fetches use `cache: 'no-store'`. Next's own data cache is not used: server-side caching lives in Redis behind FastAPI (3.14), so there is exactly one cache to reason about.
- **Streaming:** each section is its own async Server Component inside `<Suspense>` with a skeleton fallback. The shell paints at once and the sections stream in, fetched in parallel. `loading.tsx` covers navigations.
- **Errors:** a section that gets an API error renders an inline error card with the `request_id`, so one failing section never blanks the page. `error.tsx` catches the rest.

**Writes (Server Actions):**

- Every write is a Server Action in `features/*/actions.ts`: validate with the shared zod schema, call FastAPI server-to-server, return `{ ok: true }` or `{ ok: false, error: { code, message, requestId, fieldErrors } }`, then `revalidatePath` the team page so the actor's own view re-renders with fresh server data in the same round trip.
- Forms are plain `<form action={…}>` with `useActionState` for pending state and field errors, so they also work before hydration. Quick toggles (score edit, To-Do done, priority) use `useOptimistic`, so they feel instant and roll back on error.
- Login: the action calls FastAPI `/auth/login` and passes the returned session cookie on to the browser with `cookies().set` and the same attributes (3.15). Logout clears it.
- CSRF: Next.js accepts Server Actions only as `POST` and rejects them when `Origin` doesn't match the host, which protects the browser-to-Next hop. FastAPI's own CSRF layers (3.15) still check every call it receives.

**Live updates (server-first):**

- `LiveRefresher` (client) opens one `EventSource` per team to `/api/v1/teams/{id}/events` through the Next proxy.
- `team.changed`: `router.refresh()`, debounced ~150 ms so a burst of events causes one re-render. Next re-runs the Server Components and streams back only the RSC payload. Client state survives the refresh: open dialogs, half-typed forms, the running timer.
- `meeting.state` is also applied immediately to the timer and agenda stepper through a small client context, so a section change shows instantly even before the refresh lands. `meeting.ended` navigates everyone to the summary.
- Reconnect: one `router.refresh()`. A header indicator shows *Live* or *Reconnecting…*.
- **Why this holds up:** N attendees refreshing means N server renders. Their FastAPI reads hit the Redis cache (3.14), and the renders spread across PM2 workers (3.11). SSR is where PM2 cluster mode earns its keep.
- **Target:** under 1 s from a change to every attendee's re-render, measured in Phase 6 with two browsers. Fallback if `router.refresh` is too slow: include the changed section's data in the event and update that section client-side.

**What this replaces (decision 26):** TanStack Query and its query-key factory are dropped. Server Components own server state, Server Actions own writes, and `router.refresh` owns live updates: one data path instead of two. The typed client and the `openapi.json` drift check stay.

**Folder layout** (`*.client.tsx` marks client components, so the boundary is visible in file names):

```
frontend/src/
  app/
    layout.tsx                                   # html shell, Toaster
    login/page.tsx                               # server: user list
    (app)/layout.tsx                             # server: session gate, header
    (app)/page.tsx                               # server: redirect to first team
    (app)/teams/[teamId]/layout.tsx              # server: team gate (403/404), mounts LiveRefresher
    (app)/teams/[teamId]/page.tsx                # server: one <Suspense> per section
    (app)/teams/[teamId]/loading.tsx
    (app)/teams/[teamId]/meeting/page.tsx
    (app)/meetings/[meetingId]/summary/page.tsx  # server only
    (app)/admin/activity/page.tsx                # bonus: server only, Admins only
    healthz/route.ts
    error.tsx  not-found.tsx
  features/
    auth/       LoginButton.client.tsx, actions.ts
    team/       TeamSwitcher.client.tsx
    scorecard/  ScorecardSection.tsx, ScoreCell.client.tsx, MakeIssueButton.client.tsx, actions.ts, schemas.ts
    issues/     IssuesSection.tsx, IssueRow.tsx, NewIssueForm.client.tsx, SolveIssueDialog.client.tsx,
                AddTodoDialog.client.tsx, PrioritySelect.client.tsx, actions.ts, schemas.ts
    todos/      TodosSection.tsx, TodoDoneToggle.client.tsx, actions.ts
    rocks/      RocksSection.tsx                 # server only
    activity/   ActivityList.tsx, ActivityDiff.tsx  # bonus: server only, diff via jsdiff
    meeting/    AgendaStepper.tsx, AttendeeList.tsx, ConcludePanel.tsx, MeetingSummary.tsx,
                SectionTimer.client.tsx, FacilitatorControls.client.tsx, RatingPicker.client.tsx,
                JoinOnMount.client.tsx, actions.ts
  lib/
    api/        server.ts (server-only typed client), schema.d.ts (generated), errors.ts
    realtime/   LiveRefresher.client.tsx, MeetingStateContext.client.tsx
    time/       format.ts, useMeetingTimer.ts
    permissions.ts
  components/ui/                                 # shadcn/ui
```

**Build once, use twice (brief 2.5):** `ScorecardSection` and `IssuesSection` are Server Components taking `{ teamId, mode: 'team' | 'meeting' }`. In meeting mode the Scorecard highlights the last closed week and Issues use a compact, IDS-friendly layout. The client islands and actions inside them are identical in both modes.

**Typed client:** a script exports FastAPI's OpenAPI document to a committed `openapi.json`; `npm run gen:api` turns it into `lib/api/schema.d.ts` (`openapi-typescript`) for the `openapi-fetch` client. A test regenerates `openapi.json` and fails if it differs from the committed copy, so the frontend types can't silently drift from the API.

**Meeting timer:** `useMeetingTimer` computes a clock offset from the latest `server_now` (from the server render or a `meeting.state` event), then renders `section_duration - (now + offset - section_started_at)` once per second. Below zero it shows **Over time +mm:ss** in red. It never advances anything; only the facilitator's click does.

**Meeting page:** joins automatically once on load (`JoinOnMount` calls the idempotent join action; joining in a render would be a side effect in a GET). Layout top to bottom: agenda stepper (Scorecard 5 min, IDS 60 min, Conclude 10 min) with the big timer, attendee list, then the current section. Everyone sees the section the facilitator is on. The facilitator gets pinned *Next section* and *End meeting* buttons; ending asks for confirmation in a shadcn `AlertDialog`, never a browser `confirm()`. Conclude shows the To-Dos created in this meeting and a 1 to 10 rating picker for eligible attendees, changeable until the end. Observers see the same screens read-only. With no meeting running, the page offers *Start meeting* (Admin, Team Member) or says *No meeting running* (Observer).

**Forms and validation:** one zod schema per form in `features/*/schemas.ts`, used twice: in the client form for instant feedback, and again in the Server Action before calling FastAPI. The limits mirror the API (titles 200, notes 2000, priority 1 to 5, rating 1 to 10), but FastAPI stays the authority: its `422` field errors come back through the action and show in place.

**Time display:** every date and time is shown in the company time zone from `/me` (`America/Chicago`), never the browser's. Server rendering makes this easy: formatting happens on the server with an explicit zone, so there is no server-versus-browser hydration mismatch. Calendar dates (`due_date`, `week_start`) stay strings and are never parsed with `new Date('YYYY-MM-DD')`, which would read them as UTC midnight and show the previous day in Chicago.

**Permissions in the UI:** the server knows the user's role and teams from `/me` and renders accordingly: Observers get disabled controls with an "Observers can view only" tooltip; non-facilitators never receive facilitator controls in the HTML at all. This is presentation only: FastAPI enforces every rule (3.6).

**States and accessibility:** a skeleton per section while it streams, a clear empty state per section, inline error cards. Status always uses text plus icon, not color alone. Inline score edit: Enter saves, Escape cancels. The timer region announces section changes politely to screen readers, not every tick.

**Config:** `output: 'standalone'`, `poweredByHeader: false`, `reactStrictMode: true`, `compress: true`. The only env var is the server-side `API_INTERNAL_URL`; nothing uses the `NEXT_PUBLIC_` prefix, so no configuration or secret reaches the browser bundle.

**If time:** Vitest unit tests for the timer maths, date formatting and permission helpers.

### 3.18 Activity log: separate database, background worker, admin diff page (decisions 28 to 30, bonus rank 4)

Replaces the earlier "audit trail" bonus. Fully planned here; built only once the core is green, otherwise described in the decision record.

**Goal:** a durable, append-only record of **every change to every data table in the main database** (who, what, when, before and after), stored in its own database `eos_activity` on the same Postgres cluster, written and read by a dedicated background worker, without slowing or blocking live transactions on the functional tables. Admins browse it on a separate page with filters, full-text search and a git-style diff per change.

```mermaid
flowchart LR
    subgraph Main ["Postgres database eos, functional"]
        FT["All data tables<br/>users, teams, scores, issues, todos, meetings, ..."]
        TR["Generic row trigger<br/>on every data table"]
        OB["activity_outbox<br/>append-only hand-off"]
    end
    subgraph Act ["Postgres database eos_activity, same cluster"]
        AE["activity_events<br/>append-only, full-text indexed"]
    end
    API["FastAPI, Uvicorn workers"]
    W["Activity worker<br/>own container"]
    UI["Admin activity page<br/>filters, search, diffs"]
    API -->|"write + actor context"| FT
    FT --> TR
    TR -->|"same transaction"| OB
    API -->|"app events: login, logout, denied"| OB
    OB -->|"NOTIFY wake-up, batch with SKIP LOCKED"| W
    W -->|"idempotent batch insert"| AE
    W -->|"delete processed rows"| OB
    UI -->|"Admin only"| API
    API -->|"internal call, service token"| W
    W -->|"filtered, searched, keyset query"| AE
```

**Capture: one generic trigger on every data table (decision 30).**

- A single PL/pgSQL function `log_row_change()` is attached as an `AFTER INSERT OR UPDATE OR DELETE … FOR EACH ROW` trigger to **every data table** in the main database: `companies`, `users`, `teams`, `memberships`, `measurables`, `scores`, `rocks`, `milestones`, `issues`, `todos`, `meetings`, `meeting_attendees`, `meeting_ratings`, `meeting_summaries`. A statement-level `AFTER TRUNCATE` trigger logs one event per truncated table (test resets, `seed --reset`).
- It writes one outbox row: table name, operation, primary key, `to_jsonb(OLD)`, `to_jsonb(NEW)`, transaction id (`txid_current()`), timestamp and the actor context.
- **Actor context:** at the start of every write transaction the API runs `set_config('eos.actor_id', …, true)` plus `eos.actor_name`, `eos.request_id` and `eos.source` (all transaction-local). The trigger reads them with `current_setting(…, true)`. Writes with no context (seed, migrations, manual SQL) are logged as actor `system` with source `seed` or `system`.
- **Noise filter:** an `UPDATE` whose only changed columns are bookkeeping (`teams.cache_version`, row `version` counters, `updated_at`) is skipped, so the cache bump in every write (3.14) doesn't produce an event of its own. `clock_anchor` and `activity_outbox` itself have no trigger.
- **Why triggers instead of app code:** coverage is guaranteed. Every path that changes data (API, seed, a manual `psql` fix) is logged, and a new endpoint can't forget to log. A test asserts that every data table has the trigger.
- The function is `SECURITY DEFINER` (owned by `eos_owner`, `search_path` pinned), so the API's role needs no privileges on the outbox at all.
- App-level events that change no table (login, logout, refused access) go into the outbox through a second `SECURITY DEFINER` function, `log_app_event()`, which is all `eos_app` may execute.

**Hand-off: transactional outbox, not a queue.**

- The outbox row is written **in the same transaction** as the change. If the change rolls back, so does its log row; if it commits, the log row is guaranteed to exist. No lost events, and no events for changes that never happened.
- Redis Streams was considered and rejected: Redis is a non-persistent cache that is allowed to fail (3.14), so events could be lost, and making it durable would change its role. Celery or a separate broker adds a service for no gain at this size.
- Everything heavy (field diffs, readable summaries, name lookups, search indexing, writing to the second database, serving queries) happens in the worker, never in the request.

**Why live transactions are not disturbed:**

- The trigger adds one append-only insert per changed row (no foreign keys, so no extra locks on functional rows): tens of microseconds per row. That is the whole cost inside the live transaction.
- The worker **never writes to or locks functional tables.** In the main database it locks only outbox rows, selecting batches with `FOR UPDATE SKIP LOCKED`, so neither side ever waits for the other. For readable names it may read reference rows (users, teams, measurables, rocks, meetings) with plain `SELECT`s, cached in an in-memory LRU; in Postgres plain reads take no row locks and never block writers or get blocked by them.
- Activity data lives in a different database: separate tables, locks, autovacuum and permissions, so activity queries and full-text searches can't contend with functional tables.
- The worker's connections are capped (2 to the main database, 3 to the activity database) and its batches are small (up to 500 rows, short transactions under `statement_timeout`), so it can't starve the API's pools (3.12).
- Honest limit: one cluster still shares CPU, disk and WAL. Moving `eos_activity` to its own server later is only a connection-string change (1,000-companies note).

**Processing loop** (`backend/app/activity/worker.py`):

1. Wake on `NOTIFY activity_outbox` (sent by the trigger inside the writing transaction, so delivered only after commit), or every 2 s as a fallback.
2. Short main-database transaction: `SELECT … FROM activity_outbox ORDER BY id LIMIT 500 FOR UPDATE SKIP LOCKED`.
3. Build the events: team id (from the row, or from its parent for `scores`, `milestones` and meeting child tables), field-level `changes`, a readable summary from a per-table template, and the search text. Insert them into `eos_activity` with `ON CONFLICT (id) DO NOTHING`; commit.
4. Delete those outbox rows; commit the main-database transaction.

A crash between steps 3 and 4 only reprocesses the batch, and the outbox id as primary key turns the second insert into a no-op: at-least-once delivery plus an idempotent insert means every event is stored exactly once. `SKIP LOCKED` would also let several workers share the load; one is enough here. The outbox table gets aggressive autovacuum settings because it is constantly inserted into and emptied. On first start the seed produces a few hundred events (source `seed`); the worker drains them in seconds. The triggers come with the main schema migration, so they also exist in `eos_test` and `eos_report`, where no worker runs: tests drain their outbox themselves with `drain_outbox()`, and the rules report truncates its scratch database on every run, so neither outbox grows without bound.

**Activity database `eos_activity`** (full schema in `docs/DB_SCHEMA.md`):

- One table, `activity_events`: id (the outbox id), time, transaction id, source (`app`, `seed`, `system`), team, actor id and name snapshot, table name, operation, row id, action, summary, `changes`, full `before` and `after` row snapshots, `request_id`, meeting id, and a generated full-text `search` column with a GIN index.
- No foreign keys into the main database (impossible across databases), so names are copied in when the event is written and stay historically correct.
- Append-only by permission: the worker's role there can only `INSERT` and `SELECT`; no app role can update or delete an event.
- Its own Alembic environment (`backend/alembic_activity/`), run by `migrate`.

**Reads (Admins only, decision 28):**

- One endpoint, `GET /api/v1/activity`, with filters and search (listed under the page below) and keyset pagination `before=<id>&limit=50`. It is the only paginated endpoint, because logs grow without bound. Contract in `docs/API_CONTRACTS.md`.
- The main API checks access (Admin) with the same policy as everything else, then forwards the query to the worker's internal endpoint. The worker answers from `eos_activity`; the API never connects to that database.
- The worker's HTTP port (`8100`) is **internal only**: not published to the host, and every call needs the shared service token `ACTIVITY_SERVICE_TOKEN`, so nothing reaches it without passing the API's authorization.

**Admin activity page** (`/admin/activity`, decisions 29 and 30):

- A separate page, Admins only. Its server component checks `/me`: non-Admins get the same "no access" page as for a foreign team, and the API refuses them anyway (`403`). The header shows an *Activity* link only to Admins.
- **Filters** (all combinable, all in the URL so a filtered view can be bookmarked or shared):

  | Filter | Values |
  |---|---|
  | Team | any team, or company-level only |
  | Table | any data table, or app events |
  | Operation | insert, update, delete, truncate, app event (login, logout, denied) |
  | Actor | any user, or `system` |
  | Source | app, seed, system |
  | Date range | from / to, in company time (Chicago) |
  | Row | exact row id, for example `i5` (full history of one record) |
  | Request | exact `request_id` (everything one request changed, matching Dozzle) |
  | Meeting | everything changed during one meeting |

- **Search:** one box for full-text search over summaries and before/after values, using Postgres `websearch_to_tsquery`, so `"carrier pickup"`, `pickup -delay` and `priority OR solved` work as people expect. Matches are highlighted on the server with `ts_headline`. Input is capped at 200 characters.
- The filter bar is a plain `GET` form and *Load older* is a plain link (`?before=<id>` keeping all filters), so filtering, searching and paging all work without client JavaScript. A *Clear filters* link resets the view.
- **Grouped like commits:** events from the same transaction appear under one header (time, actor, request, how many rows changed), like a git commit touching several files. For example, ending a meeting shows the `meetings` update and the new `meeting_summaries` row together.
- **Git-style diff per row change**, expandable with a native `<details>` element:
  - Field by field, like `git diff`: old values on red `-` lines, new values on green `+` lines. Unchanged fields are hidden behind a *show unchanged* toggle (also `<details>`), like diff context.
  - An insert shows only `+` lines; a delete or a cleared score shows only `-` lines.
  - Long text (titles, resolution notes) gets a word-level diff inside the line, like `git diff --word-diff`: removed words struck through in red, added words in green.
  - The worker computes the `changes` list (`[{field, old, new}]`) once, when the event is written. The word-level highlighting is computed on the server at render time with the `diff` (jsdiff) package. No diff code ships to the browser.
  - Colors always come with `-` / `+` markers and screen-reader labels ("removed", "added"), never color alone.

```
Nov 11, 10:02 AM · Harper Hill · request req_51ab07e3 · 2 rows changed
  issues i9 "Carrier pickup delays" · update
  - solved_at: (empty)
  + solved_at: Nov 11, 10:02 AM
  + resolution_note: Switched carrier pickup to 7 AM.
  todos t_8x2k1m4q · insert
  + title: Call carrier about pickup window
  + owner: Harper Hill
  + due_date: 2026-11-18
  + source_issue: i9
```

**Failure behavior:**

- Worker down: the API keeps working and outbox rows pile up; the worker catches up after restart. `/healthz` reports `activity_backlog` (row count, oldest age) and turns `degraded` once the oldest row is over 5 minutes old.
- Activity reads while the worker is down: `503 activity_unavailable` for that endpoint only.

**Operations:** compose service `activity` (same backend image, command `python -m app.activity`), healthcheck on its internal `/healthz`, Dozzle name `activity worker` in the `app` group, so its logs sit beside the backend and frontend streams. Connection names `eos-activity:outbox:<hostname>:<pid>` and `eos-activity:store:<hostname>:<pid>`.

**Roles** (3.15):

- `eos_app` has **no** privileges on `activity_outbox`; it may only `EXECUTE log_app_event()`. The triggers write the outbox as `SECURITY DEFINER` functions.
- `eos_activity_consumer` (worker, main database): `SELECT` and `DELETE` on `activity_outbox`, `SELECT` on reference tables for names. Nothing else.
- `eos_activity_writer` (worker, activity database): `INSERT` and `SELECT` on `activity_events` only, which makes the log append-only.
- `eos_owner` owns both schemas for migrations.

**Tests:**

- **Coverage:** a catalog query asserts that every table in the main schema except `clock_anchor` and `activity_outbox` has the row trigger and the truncate trigger, so a new table can't be added without logging.
- Each kind of write produces exactly one event per changed row once the outbox is drained (tests call `drain_outbox()` directly instead of waiting); the seed's events carry source `seed`; a cache-version-only update produces none; `TRUNCATE` produces one event per table.
- A rolled-back write produces no event.
- Processing the same batch twice, or two workers draining at once, never duplicates an event.
- Non-blocking: while a worker transaction holds a batch, an API score edit still commits in under 200 ms.
- Filters and search: each filter narrows correctly, combinations work, `websearch` syntax (quotes, minus, OR) behaves, keyset paging with filters returns no gaps or repeats.
- Security: the activity role cannot `UPDATE` or `DELETE` events; `eos_app` cannot read or write the outbox directly; the worker's internal endpoint rejects calls without the service token; non-Admins get `403` from `/activity` and the "no access" page at `/admin/activity`.
- Diff rendering: a priority change shows one `-` and one `+` line; a changed resolution note shows word-level highlights; a transaction with two rows renders as one group (server HTML snapshot).

**Estimate:** ~5.5 h (bonus): triggers and capture 1.0, worker 1.0, activity database and roles 0.5, read endpoint with filters and search 1.0, admin page with grouping and diffs 1.25, tests 0.75.

---

## 4. Seed data findings (hand-checked, use as test oracles)

Verify each against the code when the rules module exists. These are my hand calculations, not the graders' answers.

| Rule | Case in seed | Expected |
|---|---|---|
| Weeks | 13 weeks `2026-08-17 .. 2026-11-09` | `11-09` is the current week at default `APP_NOW` |
| Status, closed week with no score | `m5` (Cash on hand) has no score for `10-19` and `11-02` | `off_track` |
| Status, current week | Only `m5` has a score for `11-09` (520, goal >= 500) | `m5` `on_track`; `m1 m2 m3 m4 m6 m7` `pending` |
| Status, boundaries | `m2` = 3.0 (at_most 3.0), `m3` = 2.0 and 4 (between 2..4), `m5` = 500, `m6` = 50, `m1` = 10 | all `on_track` |
| Status, just outside | `m3` = 4.1, 4.5, 1.8; `m2` = 3.1 | `off_track` |
| Status, `exactly` | `m4` = 0 and 2 (goal 1) | `off_track` |
| Completion, exact 90% | Leadership week `11-02`: 10 due, 9 done (`t29` done 06:01Z = 00:01 Monday Chicago, after its week) | `{due:10, done:9, rate_percent:90, meets_target:true}` |
| Completion, last-minute done | `t28` done `2026-11-09T05:59Z` = 23:59 Sunday Chicago | counts as done in week `11-02` |
| Completion, DST trap | `t11` due 10-30, done `2026-11-02T05:30Z` = 23:30 Sunday Nov 1 Chicago | done in week `10-26`. UTC bucketing or a fixed -5 offset gets this wrong. Week `10-26` = 3 due, 2 done, 67% |
| Overdue (today = 2026-11-11 Chicago) | `t12` (due 11-01), `t31` (due 11-10); `t30` is due today | Leadership overdue = `[t12, t31]`; `t30` not overdue |
| Rock `r1` | Milestone `ms2` due today, not done | not past due, so `on_track`, 1/3 = 33% |
| Rock `r2` | `ms5` due 11-10, not done | `off_track` (seeded `on_track`), 1/8 = 12.5% = **13%** |
| Rock `r3` / `r4` / `r5` | No milestones | `complete` 100% / `off_track` 0% / `on_track` 0% |
| Issue order (Leadership unsolved) | `i2` (p5, oldest), `i1` (p5), `i5` (p4), `i3` (p3), `i4` (no priority) | `[i2, i1, i5, i3, i4]` |
| Make it an Issue dedupe | `m1` week `11-02` already has open `i5` | returns `i5`, creates nothing |
| Make it an Issue after solve | `m4` week `10-26` has only solved `i6` | creates a new Issue |
| Rating rounding | `mt1` = (8+9+7)/3, `mt2` = (8+9+8+8)/4 = 8.25 | `8.0` and **`8.3`** (half up) |
| Meeting weeks | `mt1` started Wed 10-28, `mt2` Wed 11-04 | reviewed weeks `10-19` and `10-26` |
| Meeting attribution | `i7`/`t20` fall inside `mt1`; `i6`/`t30` inside `mt2` | `issues_solved` / `todos_created` by time window |
| Observer attendee | `u5` attended both meetings, never rated | in `attendee_ids`, excluded from rating |
| Cross-team access | `u2` in Leadership + Sales, `u4` in Leadership + Operations, `u1` Admin listed only in Leadership | team switcher: Admin sees all three; `u1` is an eligible owner in every team (decision 5) |

Also: `m5` has a score in the **current** week but gaps in two closed weeks, so the Scorecard grid must render missing cells, not assume a dense array.

---

## 5. Phased build plan (~20.5 h left, graded core first)

**Order (decision 31):** build the graded journey end to end first, on the simplest settings, then add the platform layers you chose (multiple API workers, PM2 cluster, Redis cache, CSP and rate limits, observability polish). Every layer sits behind a config switch, so an unfinished one can ship switched off instead of breaking the app. Nothing is dropped; only the order changes. If time runs short, the slip lands on layers, not on graded features.

**Designed in from day one**, so the layers need no rework later: `NOTIFY`-based real-time fan-out (it works with one worker too), the database clock anchor, and the `teams.cache_version` bump as the first statement of every team write (3.14).

### Graded core (~15.25 h)

| # | Phase | Hours | Exit criteria |
|---|---|---|---|
| P | **Prerequisite: Docker setup** (section 0) | done | `docker run --rm hello-world` works (confirmed 2026-11-23) |
| 0 | **Lean scaffold**: repo, compose with `db`, `migrate`, `api`, `web`, `logs` (plain Dozzle) and `info` (banner skeleton), `.env.example`, `db/init/`, FastAPI hello + `/healthz`, Next.js + shadcn + Tailwind standalone build (plain `node server.js`), Alembic wired, Makefile, lint/format config, JSON request logging and error handler | 1.5 | Clean `docker compose up` prints the banner: web `:3000`, API `:8000`, docs `:8000/docs`, logs `127.0.0.1:8080`, Postgres `127.0.0.1:5433` |
| 1 | **Rules module + clock + tests** (pure code, no DB): section 3.4 functions, week and DST maths, rounding | 1.5 | Rule tests green, including every row of section 4 |
| 2 | **Schema, migrations, seed, connections**: everything in `docs/DB_SCHEMA.md` except the bonus objects (tables, constraints, role triggers, indexes, `teams.cache_version`, `clock_anchor`), least-privilege roles, idempotent seed (`ON CONFLICT DO NOTHING`, `--reset`), banner user table from the DB, pool lifecycle with application names (3.12) | 2.0 | Fresh DB seeds twice with identical state; app edits survive a restart; `pg_stat_activity` shows the expected `application_name`s; `eos_app` cannot run DDL |
| 3 | **Rules report**: command with its own scratch database (`eos_report`), committed `rules_report.json` | 0.5 | Output matches the section 4 oracles. Early on purpose: graded hard, and it de-risks the rules |
| 4 | **API + authz + core security**: every endpoint in `docs/API_CONTRACTS.md` except the bonus activity endpoint, authz policy with the route-table test, Make it an Issue concurrency, validation and mass-assignment limits, session cookie, CSRF (custom header + `Origin`), JSON-only writes, body limit, basic security headers, `cache_version` bump first in every team write | 3.0 | Contract examples pass as API tests; route-table authz test green; 20-way concurrent Make it an Issue returns one Issue; CSRF and validation tests green |
| 5 | **Meetings + real-time**: start, join, advance, end, rating, frozen snapshots (including the seeded ones), team SSE stream with `NOTIFY` fan-out and reconnect (the shared clock anchor landed in Phase 4, decision 38) | 2.5 | Two `curl` clients follow a meeting in under 1 s; refresh and reconnect restore state; an ended summary doesn't change after later edits; SSE survives a 2-minute idle through the Next proxy |
| 6 | **Frontend** (3.17): login switcher, team switcher, Team page as streamed Server Components, Server Actions with zod, client islands only where needed, Meeting page with timer and facilitator controls, summary page, `LiveRefresher` | 3.0 | Full journey clickable as Team Member, read-only as Observer, two browsers in sync |
| 7 | **E2E + test polish**: two-browser Playwright test, SSR check, XSS check, contract drift check, failure trace artifact, single `make test` | 1.25 | Unattended run green from a clean clone. **Graded core complete** |

### Platform layers (~4.0 h, each behind a switch)

| # | Layer | Hours | Exit criteria |
|---|---|---|---|
| L1 | **Multi-worker API** (3.13): `API_WORKERS=2`, deterministic cross-worker fan-out test, E2E rerun with 2 workers | 0.5 | **Done** (v31): cross-worker test and E2E green. Reviewed (v32): startup preflight, so a worker that cannot start stops the container instead of looping |
| L2 | **PM2 cluster for web** (3.11): `pm2-runtime`, `ecosystem.config.cjs`, JSON logs with worker ids | 0.5 | **Done** (v31): banner shows `pm2 cluster x2`; E2E green with 2 web workers. Reviewed (v32): a stop during worker start-up is no longer swallowed |
| L3 | **Redis cache** (3.14): `redis` service, client lifecycle, demo-seed generation bump, cache-aside for every listed item, stampede guard, cache tests, API suite rerun with the cache off | 1.75 | **Done** (v33): cache tests green; byte-identical responses with `CACHE_ENABLED=false`; 433 tests with the cache on, 420 off |
| L4 | **Security extras** (3.15): nonce CSP middleware, Redis-backed rate limits (needs L3's Redis), non-root and read-only containers, dependency audit | 0.75 | **Done** (v35): CSP and rate-limit tests green; audit results above (v35) for the README |
| L5 | **Observability polish** (3.10, 3.12, 3.16): Dozzle names and groups, PM2 and Uvicorn worker tags, pool leak watch and connection-budget warning, API gzip with SSE excluded | 0.5 | Backend and frontend as separately named Dozzle streams; gzip on; SSE still unbuffered |

### Wrap-up (~1.25 h)

| # | Phase | Hours | Exit criteria |
|---|---|---|---|
| 8 | **Docs and video**: README (2 pages), `docs/DECISIONS.md` (1 page), 7-minute video, link check from a logged-out window | 1.25 | Submission sent |

Total: 15.25 + 4.0 + 1.25 = **20.5 h** (the reorder adds ~0.25 h for wiring the switches).

### Layer switches

| Layer | Switch, default once built | When off |
|---|---|---|
| L1 | `API_WORKERS=2` | One Uvicorn worker; `NOTIFY` and the clock anchor work unchanged |
| L2 | `WEB_RUNNER=pm2`, `WEB_INSTANCES=2` | Plain `node server.js` |
| L3 | `CACHE_ENABLED=true` | Every read goes to Postgres |
| L4 | `CSP_MODE=nonce`, `RATE_LIMIT_ENABLED=true`, `READ_ONLY_FS=true` | Basic headers, no rate limits, writable filesystem |
| L5 | `GZIP_ENABLED=true`, `LOG_WORKER_TAGS=true`, `POOL_LEAK_WATCH=true` | Plain logs, no gzip |

Whatever ships switched off is listed in the README's known limitations. Shipping a layer off needs your OK at the time (section 9).

If phase 6 runs long, shrink styling, not behavior.

### UX notes for usability (15%)

- Scorecard: rows = Measurables, columns = 13 weeks (newest at the edge the team looks at first), color plus text for status (not color alone), inline edit with Enter to save, "Make it an Issue" only on off-track cells.
- Meeting page: agenda stepper at top, large section timer in tabular numbers, over time turns red and reads "Over time +02:13", facilitator controls pinned and clearly labeled, everyone else sees a "Facilitator: Name" badge instead of buttons.
- Observers see read-only affordances (disabled controls with a tooltip), never a button that then errors.

---

## 6. Testing plan (15%)

One documented command (`make test`, with the plain `docker compose run ...` equivalent in the README because Windows and some reviewer machines have no `make`), unattended, against seed data and a fixed clock.

| Layer | What to cover |
|---|---|
| **Rule tests** (pytest, no DB) | Every rule in 2.6 with at least one boundary: status for all four goal types at the exact boundary, no score in closed vs current week, completion exactly 90%, done after due week, zero due gives no rate, rock status and progress cases from section 4, issue order including no-priority-last, rating 8.25 to 8.3, week bucketing around DST, half-up rounding |
| **API tests** (pytest + httpx, real Postgres) | Team Member reading another team's data refused (by guessed id too); Observer write refused on every mutating route (route-table test); Admin reads all teams; **concurrent Make it an Issue returns one Issue** (`asyncio.gather` of ~20 requests: one `201`, the rest `200`); Make it an Issue on an on-track cell gives `422`; validation errors (bad priority, blank solve note, non-Monday week, rating out of range, Observer as owner); one active meeting per team (`409`); only the facilitator advances and ends; frozen summary unchanged after a later edit; **cross-worker fan-out** (start two API processes, subscribe the follower on one, advance on the other, assert the event arrives: deterministic, unlike hoping Uvicorn spreads the two browsers across workers); exhausted pool returns `503 db_busy` instead of hanging |
| **Security tests** (pytest + one E2E assertion) | Write without `X-EOS-CSRF` gives `403`; write with a foreign `Origin` gives `403`; `text/plain` body gives `415`; 65 KB body gives `413`; unknown field or `team_id` in the body gives `422`; tampered or expired cookie gives `401`; rate limit gives `429` with `Retry-After`; security headers present on `web` and `api` responses; the `eos_app` role cannot `CREATE TABLE` or `TRUNCATE`; an Issue titled `<script>alert(1)</script>` renders as plain text (E2E) |
| **Cache tests** (pytest, real Redis) | Read-your-writes: edit a score, the next Scorecard read (same worker and other worker) shows the new value and status; team isolation: cache warmed by a Leadership user, a Sales Team Member still gets `403`; Redis down: API still returns correct data and `/healthz` says `degraded`; week rollover: move the frozen clock past Sunday 23:59:59 Chicago and `pending` becomes `off_track`, not a stale cached value; ended summary served unchanged from cache. The whole API suite also runs once with `CACHE_ENABLED=false` to prove identical results |
| **End-to-end** (Playwright, `e2e/`, built in Phase 7) | Runs against an isolated stack (`api-e2e`, `web-e2e`: `eos_test`, frozen clock, reseeded per run), with two Uvicorn workers and two PM2 workers (layers L1 and L2); it also passes with both layers switched off (`WEB_RUNNER=node API_WORKERS=1`). Two browser contexts: facilitator starts the meeting, second user joins, facilitator advances Scorecard to IDS, second browser follows within 2 s; the second browser reloads mid-meeting and lands on the current section; rating, end, both on the summary. Also: a live score edit across two browsers, Make it an Issue in the UI, an XSS payload shown as text, the Observer's read-only view. SSR check: the raw HTML the Next server sends already contains the Scorecard values (a JavaScript-disabled browser would only see the skeletons, because streamed sections are revealed by React's inline script; decision 43) |

**Fixture and clock strategy (write this up in the README):**

- `APP_NOW=2026-11-11T15:00:00Z` and `APP_CLOCK_MODE=frozen` for the whole suite. Meeting timer tests use an explicit "advance clock" hook on the clock service instead of wall time, so nothing sleeps.
- Tests use Redis database index 1, flushed per test module, so they never touch the demo cache (index 0).
- `RATE_LIMIT_ENABLED=false` for the suite, except the rate-limit tests themselves.
- Tests use a separate `eos_test` database (created by `db/init/`), so `make test` never wipes the demo data you are clicking through. Reset between test modules with `python -m app.seed --reset` against `eos_test` (truncate, then reseed). No test-only endpoints in the shipped API.
- Playwright config: `trace: 'retain-on-failure'`. Commit one trace zip from a deliberately broken run (for example, temporarily make the follower ignore `meeting.state`) under `artifacts/` and mention it in the README.
- **Contract drift check:** the suite regenerates `openapi.json` from the app and fails if it differs from the committed copy, so the frontend's generated types can't fall behind the API (3.17).
- Rules report, printed: `docker compose --progress quiet run --rm --build rules-report`; at another date: `docker compose --progress quiet run --rm --build -e APP_NOW=2026-11-18T15:00:00Z rules-report` (or `make rules-report-at NOW=...`). `--build` matters: without it, `run` reuses the existing image and ignores code edits. `--progress quiet` matters too: with `-T` (no TTY), Compose writes the build progress to **stdout**, which would end up inside a redirected report (found while verifying the Phase 3 review fixes).
- Regenerating the committed `rules_report.json`: `make rules-report`. It pins `APP_NOW` to the seed's now (`2026-11-11T15:00:00Z`) whatever the shell or `.env` says, rebuilds the image, writes `rules_report.json.tmp` and only moves it into place if the command succeeded, so a failure can never leave the committed file empty. Without `make`, in PowerShell (where `>` writes UTF-16 in 5.1, and the output is pure ASCII):
  `docker compose --progress quiet run --rm --build -T -e APP_NOW=2026-11-11T15:00:00Z rules-report | Set-Content -Encoding ascii rules_report.json.tmp; if ($LASTEXITCODE -eq 0) { Move-Item -Force rules_report.json.tmp rules_report.json }`
  `Set-Content` writes CRLF line endings; that's harmless, because `.gitattributes` (`eol=lf`) stores LF on commit and the tests compare the text, not raw bytes.
- Run it at 2 or 3 dates before submitting and sanity-check what changes (done for 2026-11-18 in Phase 3: `t30` becomes overdue and `r1` goes off track once `ms2` is past due).

---

## 7. Schedule (re-cut 2026-11-24, decisions 6, 22 and 31)

Monday went to planning and the Docker setup; no build work happened. The remaining work is ~20.5 h, in the order of section 5: graded core Tuesday to Friday, platform layers and the submission on Saturday.

| Day | Hours | Phases | End-of-day check |
|---|---|---|---|
| Tue 11-24 | 4.0 | Phase 0 (1.5). Phase 1 (1.5). Start Phase 2 (1.0) | Banner prints; rule tests green |
| Wed 11-25 | 4.0 | Finish Phase 2 (1.0). Phase 3 (0.5). Start Phase 4 (2.5) | `rules_report.json` matches the section 4 oracles |
| Thu 11-26 | 4.0 | Finish Phase 4 (0.5). Phase 5 (2.5). Start Phase 6 (1.0) | **Checkpoint:** API, authz, concurrency and CSRF tests green; two `curl` clients follow a meeting |
| Fri 11-27 | 4.0 | Finish Phase 6 (2.0). Phase 7 (1.25). L1 (0.5). Start L2 (0.25) | **Graded core complete:** full journey in two browsers, `make test` green from a clean clone |
| Sat 11-28 | 4.5 | Finish L2 (0.25). L3 (1.75). L4 (0.75). L5 (0.5). Phase 8 (1.25). **Submit** | Submission sent |
| **Total** | **20.5** | | |

**Saturday guard:** start Phase 8 (docs and video) no later than 2.5 h before your planned send time, whatever layer is in progress. An unfinished layer then ships switched off and is listed in the README (with your OK at the time). Docs and the video are required deliverables; layers are not.

Ways to claw time back, in order of preference:

1. **Pre-approved cuts** (section 9 items 1 and 2: UI polish, pool extras), saving about 0.5 to 0.75 h. Applied automatically if a checkpoint fails.
2. **Last-resort cuts** (section 9 items 3 and 4: ship a layer switched off, describe-only snapshot). Each needs your OK.

**Checkpoint rule:** if Thursday's checkpoint fails, apply the pre-approved cuts at once. If the graded core isn't complete by Friday night, Saturday goes to finishing it first and the layers wait; decide which layers ship switched off that evening, not on Saturday afternoon.

**Deadline in local time:** 11:59 PM EST Saturday is 04:59 UTC on Sunday 11-29. If you are on Bangladesh time (UTC+6; Google Drive showed BDT pricing), that is **10:59 AM Sunday**, so Saturday night is real slack. Still aim to submit Saturday evening your time, and don't count on Sunday morning.

**US Thanksgiving is Thursday 11-26**, and many US teams are off Friday too. Altri sets its deadlines in EST, so if you need to email them a question, send it by Wednesday or expect a slow reply.

Video rehearsal: log in as `u1` (Avery Admin) in one window and `u3` (Casey Cho) in a second, start the meeting, make `m1` week 11-02 an Issue (returns the existing `i5`, a live demo of dedupe), solve an Issue with a To-Do, advance to Conclude, rate, end, show the summary. Spend the last 2 minutes on decisions. Optionally flash the Dozzle view to show request logs and the `request_id` trail.

---

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Docker cannot be enabled on this PC (BIOS locked) | Fall back to GitHub Codespaces the same day; nothing in the plan depends on Windows |
| Time-zone bugs near week boundaries (graders run other dates) | Rules module first, tested against section 4; one `week_of`/`week_bounds` pair, no inline tz math |
| Rules report mismatch with the answer key | Report calls the same pure functions as the API; built early (Phase 3); re-run at 2 or 3 other `APP_NOW` values |
| Float or banker's rounding | `Decimal` + `ROUND_HALF_UP` everywhere, covered by the 12.5 and 8.25 cases |
| Duplicate Issues under concurrency | DB partial unique index + `ON CONFLICT`, proven by a concurrent test |
| Authz gaps on later routes | Route-table test fails when a route lacks a guard |
| Real-time flakiness in E2E | State lives in the DB, events are hints plus snapshot-on-connect; E2E waits on UI assertions, not sleeps |
| Always-on log viewer read as a security smell | Localhost binding, redaction, one-line off switch, and an honest README security note (3.10) |
| Compose differences on reviewer machines | Pinned image tags, health checks with `depends_on: condition: service_healthy`, test from a clean clone before submitting |
| SSE through the Next.js `/api` proxy (now one of several PM2 workers) may be buffered, compressed or cut by the proxy timeout (Next's `experimental.proxyTimeout`, 30 s by default) | Heartbeat every 15 s, `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no` on the stream. Prove it in Phase 5 with a 2-minute idle test. Fallback: `EventSource` connects straight to the API on `:8000` with CORS limited to the web origin (cookies still flow, since cookies ignore ports). If the signing bonus (3.16) is built, its route-handler proxy streams SSE itself and this risk goes away |
| Pool exhaustion: SSE streams holding connections, long transactions, too many workers | SSE releases its session before streaming; short transactions; `statement_timeout` and `idle_in_transaction_session_timeout`; 5 s pool timeout returning `503`; leak-watch logs; connection-budget check at startup (3.12) |
| Stale or leaked cache data (wrong status after a write, another team's data) | Cache versions stamped in Postgres in the same transaction as each write; dates and weeks in keys; authz before every cache lookup; correctness paths bypass the cache; API suite runs with the cache on and off (3.14) |
| Activity outbox grows or bloats while the activity worker is down (bonus) | API unaffected; worker catches up on restart; aggressive autovacuum on the outbox; `/healthz` backlog warning after 5 minutes (3.18) |
| Missed real-time events when a worker's `LISTEN` connection drops | Reconnect loop, then local clients refetch their snapshot (3.12 item 3); events are hints, the DB is the truth |
| `router.refresh()` too slow for the ~1 s sync target with several attendees | Debounce bursts; apply `meeting.state` to the timer and stepper client-side at once; Redis-cached FastAPI reads and PM2 workers keep renders cheap; measure in Phase 6. Fallback: send the changed section's data in the event and update it client-side (3.17) |
| Nonce-based CSP breaks Next.js pages or shadcn components | Built late as layer L4, behind `CSP_MODE`; if it breaks pages, ship `CSP_MODE=basic` with the documented fallback `script-src 'self' 'unsafe-inline'` (3.15) |
| Writes in one team queue on the `teams.cache_version` row, or deadlock | The bump is always the first statement of a team write (consistent lock order); transactions are short; the concurrency test fires 20 parallel writes at one team (3.14) |
| A platform layer destabilizes a working app late on Saturday | Every layer is behind a switch (section 5); E2E reruns after each layer; the Saturday guard starts docs and video on time regardless |
| Over budget (~20.5 h left) | Graded core first and layers last (section 5); checkpoint rule and Saturday guard in section 7; ranked bonuses; cut order in section 9 |

## 9. Cut line and bonus ranking

**Core (must ship):** sections 2, 3.1 to 3.15, the gzip part of 3.16, and 3.17; the rules report; every test layer in section 6; README, decision record, video. Request signing (3.16) and the activity log (3.18) are bonus. Build order and layer switches: section 5.

**If behind, cut in this order:**

1. UI polish and animations (pre-approved)
2. Pool extras: the leak-watch logging (3.12 lifecycle item 7) and the connection-budget startup warning (pre-approved)
3. Only as a last resort: ship an unfinished platform layer (L1 to L5, section 5) switched off and listed in the README. Needs your OK, since each layer is one of your decisions (14, 16, 18 to 21, 23)
4. Only as a last resort: meeting snapshot back to describe-only (needs your OK, since you chose to implement it)

**Never cut:** authz tests, the concurrency test, the two-browser E2E, the rules report.

**Bonus, in this order, only after the core is green (decision 12):**

| Rank | Item | Est. | Why this order |
|---|---|---|---|
| 1 | **Lost-update protection** on scores and Issue priority: `version` column (already in schema), `ETag` on reads, `If-Match` on `PUT`/`PATCH` gives `409` with the current value when stale. Requests without `If-Match` keep "last save wins", so the core rule still holds. UI shows "changed by someone else, reload?" | 0.75 h | Cheapest, columns already planned, and it strengthens the concurrency story graded at 20% |
| 2 | **1,000-companies note** (`docs/SCALING.md`): `company_id` on every table, tenant-leading composite indexes, optional Postgres row-level security, stateless API workers, SSE fan-out through Redis or `NOTIFY` channels per meeting, partitioning scores by company later | 0.25 h | Docs only, high signal for a senior role |
| 3 | **Make it an Issue from an off-track Rock or overdue To-Do**: endpoints plus two partial unique indexes on `source_rock_id` / `source_todo_id` (columns already in schema), same concurrency pattern and tests as 3.8 | 1.0 h | Reuses the core pattern, but needs UI and tests |
| 4 | **Activity log** (3.18): every data table captured by triggers, separate `eos_activity` database, transactional outbox, background worker for writes and reads, Admin-only `/admin/activity` page with filters, full-text search and git-style diffs | 5.5 h | Altri lists an audit trail as a bonus; this is the largest bonus, so the cheaper ones go first |
| 5 | **Signed Next.js to FastAPI messages** (3.16): HMAC request and response signing with boot-time key cache, replay protection, signed SSE events, request-body gzip, signing helper and shared test vectors | 2.0 h | Your request, but not on Altri's bonus list, so the four items they named go first. Move it up if you prefer |

Any bonus item not built gets a two-line "how I would do it" note in the decision record instead.

## 10. Remaining default calls (not asked, change any of them)

| Topic | Default |
|---|---|
| `403` vs `404` for an inaccessible team | `403`, documented |
| Score editing window | Any of the 13 shown weeks; clearing a score is allowed and turns the cell back to "no score" |
| Meeting attribution of Issues and To-Dos | By team and time window (3.7) |
| Starting a meeting when one is active | `409` with the active meeting id, so the UI offers "Join" |
| New To-Do due date | Today in company time + 7 days |
| Package managers | npm (already installed) for the frontend, `uv` inside the API container |
| Command runner | Makefile, with raw `docker compose` commands next to each target in the README |
| API docs location | Served by the backend at `:8000/docs` (Swagger UI) and `:8000/redoc`, no extra container. A separate docs port is a ~10 min add if you want one |
| Host port binding | Postgres and logs on 127.0.0.1 only; web and api on 127.0.0.1 by default, `BIND_ADDR=0.0.0.0` opens them to the LAN |
| Seed on restart | Seeds once per database (skips when the seed company exists), so edits and deletes survive; `docker compose down -v` for a clean slate |
| PM2 worker count | `WEB_INSTANCES=2` in `.env`; `max` is possible but uses every CPU thread |
| API worker count | `API_WORKERS=2` in `.env` (3.13) |
| Pool sizes | 5 + 5 overflow per API worker, 5 s pool timeout, 1800 s recycle (3.12) |
| Brief mentions a zip and `assessment-brief.pdf`; Drive has `assessment-brief.docx` and loose files | Same content, no action |
| AI tooling disclosure | Keep a running note while building (what AI did, what you checked) for the README. Read everything generated, since Altri may ask about any part |

---

## 11. Definition of done

- [ ] `docker compose up` from a clean clone: migrations and seed run automatically, the banner prints endpoints and users; web `:3000`, API `:8000`, docs `:8000/docs`, logs `127.0.0.1:8080`, Postgres `127.0.0.1:5433`, Redis `127.0.0.1:6379`
- [ ] Seed script rerun leaves state unchanged
- [ ] Security tests green; headers checked in the browser; `pip-audit` and `npm audit` results noted in the README
- [ ] `make test` (and its raw command) green, unattended
- [ ] `rules_report.json` committed and reproducible with the documented command
- [ ] README (with security notes for the log viewer), `docs/DECISIONS.md`, trace artifact committed
- [ ] Video recorded, link opens in a logged-out window
- [ ] Repo public, all links checked while logged out, reply sent before the deadline
