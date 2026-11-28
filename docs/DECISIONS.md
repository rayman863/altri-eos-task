# Decision record

The five decisions the brief asks about (section 2.8), each with its cost. Every other choice is in the decision log of [DEVELOPMENT_PLAN.md](../DEVELOPMENT_PLAN.md).

**1. Data model: the database refuses bad data on its own.** An Issue records its source in typed columns (`source_kind`, `source_measurable_id`, `source_week_start`), not a text blob, and a To-Do points at its Issue with `source_issue_id`. Composite foreign keys such as `(source_measurable_id, team_id)` keep every link inside one team, CHECK constraints refuse impossible states (a solved Issue without a note, an out-of-range score), and triggers enforce the owner rule. Scores are `NUMERIC`, never floats; the rules are pure functions shared by the API, the summaries, the rules report and the tests. *Cost:* more constraints to migrate, in exchange for bugs that fail loudly instead of corrupting data. ([schema](DB_SCHEMA.md))

**2. API: one documented contract, computed on the server.** REST under `/api/v1`; one error envelope with named codes; decimals as strings; every status, overdue flag and rate computed by the API, never the browser. One access policy guards every route, checked before any cache lookup; an inaccessible team is `403` even when it doesn't exist, so ids can't be probed. A route-table test fails any route added without a guard, and the committed `openapi.json`, which the web app's types are generated from, must match the code. *Cost:* no pagination (one company's data) and a stricter API to evolve. ([contracts](API_CONTRACTS.md))

**3. Real time: Server-Sent Events plus REST, with the meeting state in Postgres.** Every action is an ordinary REST write; the server pushes events over SSE. The database owns the meeting (section, timer start, facilitator), so a reload, a late join or a reconnect just reads it again, and every stream starts with a snapshot. Events go out through Postgres `NOTIFY`, which delivers only on commit and reaches every API worker, so two browsers on different workers stay in step (tested across two real processes). *Cost:* SSE is one-way, which is all this needs; it passes proxies and reuses the REST access checks, where WebSockets would add a protocol and its own auth. At real scale the fan-out moves from `NOTIFY` to Redis pub/sub ([scaling](SCALING.md)).

**4. "Make it an Issue" can't make duplicates.** A partial unique index allows one open Issue per Measurable and week; the insert is `ON CONFLICT DO NOTHING`, then the existing Issue is read and returned (`201` new, `200` existing). Every team write also takes the team's row lock first (it bumps the cache version), so simultaneous clicks queue and the index is the backstop, not the usual path. A test fires 20 requests at once and gets exactly one Issue. *Cost:* writes in one team serialize; at tens of writes an hour per team that is invisible, and a fixed lock order rules out deadlocks.

**5. Past summaries never change.** Ending a meeting writes a frozen snapshot (attendees, Scorecard statuses for the reviewed week, Issues solved, To-Dos created, the rating, and the names it needs) in the same transaction. The summary page reads that snapshot and never recomputes it, so later score edits can't rewrite history (tested). *Cost:* duplicated data, about 5 KB per meeting. The rules report is the one deliberate exception: it recomputes from a fresh seed at any `APP_NOW`, because that is what it is graded on.

## Beyond the five

Built behind switches, each reviewed: two API workers, a PM2 cluster for Next.js, a Redis cache keyed by Postgres versions (it can't serve stale data), a nonce CSP with rate limits and locked-down containers, and observability (worker-tagged logs, a leak watch, gzip). Bonuses built: lost-update protection (`If-Match` on score and priority edits) and the [1,000-companies note](SCALING.md).

**Not built, and how I would do it:**

- **Activity log:** row triggers write an outbox in the same transaction; a worker moves it into a separate append-only database, behind an Admin page with search and before/after diffs (plan, section 3.18).
- **Signed Next.js-to-API requests:** HMAC-SHA256 over method, path, timestamp, nonce and body hash, keys derived per direction, nonces single-use in Redis, responses signed against the request nonce. Proves origin, not privacy (that needs TLS).
- **Make it an Issue from a Rock or To-Do:** the source columns exist; add two partial unique indexes and reuse the Measurable endpoint's pattern and concurrency test.
