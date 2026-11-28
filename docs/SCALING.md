# Scaling to 1,000 companies

What would change to serve 1,000 companies from this codebase, in the order I would do it. Bonus item 2 of the brief: a design note, not built. Much of the groundwork already exists, because the API was built to run as several stateless workers (platform layers L1 to L5). The real gaps are **tenant isolation**, **logins**, **ids** and **connection count**.

## 1. The load, roughly

| Assumption | Figure |
|---|---|
| Companies, teams, users | 1,000; ~5 teams each (5,000 teams); ~50 users each (50,000 users) |
| Meetings | One Level 10 a week per team: 5,000 a week, ~8 attendees each |
| Peak | Meetings cluster at the top of the hour on weekday mornings in each time zone. Say 20 % of teams meet in the same hour: ~1,000 concurrent meetings and ~8,000 open live streams |
| Peak writes | ~1 to 3 a minute per meeting: ~20 to 50 writes a second |
| Peak reads | Every write sends a live event, and each of the ~8 attendees' pages re-renders, reading ~5 read models: ~40 reads per write, so roughly **1,000 to 2,000 reads a second** |
| Data per year | Scores ~1.5 million rows, Issues and To-Dos ~3 to 5 million, meeting summaries ~260,000 (about 5 KB each, ~1.3 GB) |

**Measured today**, from inside the Docker network on a laptop (with the load generator on the same machine, so these are floors): one `api` container with 2 Uvicorn workers serves **~400 authenticated Scorecard reads a second** at 32 concurrent requests (p50 50 to 80 ms), whether payload logging is on or off; with 4 workers, ~570 a second. Peak load therefore means a handful of API replicas, not a different architecture. Postgres is not the limit at this size: a cached read costs two small primary-key lookups (the session epoch and the team's version), plus one more for Admins (does the team exist).

## 2. Tenant isolation: must change first

Today there is one company. Boundaries are enforced per **team** (one policy in `app/authz.py`, a route-table test, same-team composite foreign keys, role triggers), but `company_id` exists only on `users` and `teams`, and the **Admin role assumes a single company**: an Admin passes every team (`CurrentUser.can_read`), lists every team (`services/teams.py`), and every Admin counts as an eligible owner on every team (`services/common.py`, `_team_ref`, the owner role trigger). With a second company, that is a cross-tenant leak.

1. **`company_id` on every tenant table** (memberships, measurables, scores, rocks, milestones, issues, todos, meetings, attendees, ratings, summaries), with composite foreign keys `(company_id, team_id) → teams (company_id, id)`. That extends the existing same-team composite keys, so a row can never point into another company.
2. **Admin means company admin.** `can_read(team)` becomes "same company, and admin or member"; the team list and eligible owners filter by company; the role trigger checks the company. The route-table test gets a second seeded company, and every route must refuse its ids, for Admins too.
3. **Row-level security as a backstop.** Each transaction starts with `SELECT set_config('app.company_id', :company, true)` (the same "first statement" pattern as today's team-version bump). Every tenant table gets a policy `USING (company_id = current_setting('app.company_id'))`. `eos_app` is not the table owner and has no `BYPASSRLS`, so a query that forgets its filter returns nothing instead of another company's rows.
4. **Tenant-leading indexes:** `(company_id, team_id, ...)` in place of today's team-leading ones (`ix_issues_team_id_solved_at`, `ix_rocks_team_id_quarter`, the partial unique indexes for Make it an Issue and one active meeting).
5. **One shared schema**, not a schema or database per tenant: 1,000 small tenants, one migration path, pooled connections, and isolation from the policies above. A database per tenant only for the few customers who need data residency.

## 3. Logins

The seeded user switcher and the public `/auth/users` list go. Sign-in becomes OIDC or SSO per company (email domain to company), and the session cookie carries the company id next to the user id and the session epoch. Logout and epoch invalidation keep working as they do now.

## 4. Ids

New rows get 8 random base-36 characters (`services/common.py`): about 2.8 × 10¹² values, so by the birthday bound a collision becomes likely somewhere around 2 million rows in one table. That is about a year of To-Dos at this scale. New ids should be UUIDv7 (time-ordered, which keeps B-tree inserts local) or 16 random characters, with a retry on a unique violation. Seed ids keep their readable form.

## 5. API and web tiers

**Already stateless:** sessions are signed cookies (the logout epoch lives in Postgres); meeting state, the shared clock anchor and cache versions live in Postgres; the cache and rate limits live in Redis. Any worker can serve any request, which `tests/api/test_processes.py` proves across two real processes.

- **From workers to replicas:** N `api` containers behind a load balancer, with no sticky sessions, each running Uvicorn workers (with the startup preflight). The load balancer's idle timeout must exceed the 15 s SSE heartbeat. Next.js scales the same way: replicas, with one process per container once the orchestrator restarts crashed containers (PM2's job inside one container today).
- **Connections:** today `2 workers × (5 + 5 overflow + 1 LISTEN) = 22` of Postgres's 100 (logged at startup by the L5 budget check). Eight replicas would need 176, so the pools go through **PgBouncer** in transaction mode. asyncpg's prepared statements then need PgBouncer 1.21+ (`max_prepared_statements`) or statement caching switched off, and the `LISTEN` connections must bypass PgBouncer, because `LISTEN` is session state (or real-time moves off Postgres, section 6).
- **Read replicas:** not needed first. The Redis cache absorbs the meeting fan-out, and the cache-version read must hit the primary anyway, since it is what guarantees a reader never sees data older than the last write.

## 6. Real-time fan-out

Today every write sends one Postgres `NOTIFY` on one channel at commit; every worker receives every team's events and passes them to its own open streams; events are hints, and each (re)connect starts with a full snapshot. At 8,000 streams the streams themselves are cheap (async, a few KB each). The limits are elsewhere:

- every worker parses every event (cost grows with workers × events), which is fine up to a few dozen workers;
- `NOTIFY` takes a database-wide lock at commit, which serializes committing transactions that notify. That is fine at tens of writes a second and becomes the ceiling well before the database does;
- payloads are capped at 8,000 bytes (already handled: oversized events become a `team.changed` hint).

**Next step:** Redis pub/sub (or NATS) with one channel per team. Each worker subscribes only to teams that have an open stream on it, and messages are published after commit (an after-commit hook, or an outbox for guaranteed delivery), so only committed changes are ever announced. The snapshot-on-connect stays, so a lost message still costs nothing but a refresh.

## 7. Cache

Already multi-tenant safe: keys carry the database, a hash of the API source, a generation and the team's version (`app/cache.py`), and access is checked before any lookup. The working set is the read models of teams that are currently active, tens of KB per team, so a few hundred MB at peak: raise `maxmemory` from 128 MB to about 1 GB and keep LRU. There are no hot keys, because every entry is per team. Once companies can edit their own reference data (users, teams, Rocks) through admin screens, the seed-wide generation becomes one generation per company, bumped by those writes.

## 8. Time

`APP_NOW` and the ticking business clock exist for this assessment. Production reads the real clock (a third clock mode). Company time zones already drive week boundaries and "today" (`rules/weeks.py`), so companies across time zones need no other change.

## 9. Operations

- **Logs:** they already carry the request id and worker on every line; add the company id. Dozzle (which needs the Docker socket) gives way to centralized logging such as Loki or ELK, with payload logging off.
- **Metrics:** request rate and p95 per tenant, cache hit ratio, pool usage (already on `/healthz`, per worker), `NOTIFY` or pub/sub lag, alerts on the connection-budget and leak-watch warnings.
- **Noisy neighbours:** rate limits per company tier, on top of today's per-user and per-address limits.
- **Data:** point-in-time recovery backups; per-company export and deletion by `company_id`; range partitioning only once a table warrants it (scores by year; the activity log, if built, by month).

## 10. Order of work

1. Tenant isolation: `company_id` everywhere, company-scoped Admin, second-company tests, row-level security. This is correctness, and it comes before customer number two.
2. Real logins (OIDC or SSO), with the company in the session.
3. New id format.
4. PgBouncer, then API and web replicas behind a load balancer.
5. Per-team pub/sub for live updates.
6. Per-tenant observability and rate limits.
7. Partitioning and retention, when the data calls for it.
