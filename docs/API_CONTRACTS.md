# API Contracts

Planned REST API for the EOS / Level 10 Meeting app. **Status: planning.** FastAPI will publish the same contracts as OpenAPI at `/docs`; this file is the agreed design, and the committed `openapi.json` must match it (drift check, plan section 3.17).

Examples use the seed data at the default `APP_NOW` (`2026-11-11T15:00:00Z`, Wednesday 9:00 AM Chicago). They are hand-computed and double as test expectations.

## 1. Conventions

| Topic | Rule |
|---|---|
| Base path | `/api/v1`. Breaking changes would go to `/api/v2`; within v1 changes are additive only. Exceptions at the root: `GET /healthz` (container healthcheck) and the docs (`/docs`, `/redoc`, `/openapi.json`) |
| Format | JSON (`application/json; charset=utf-8`), UTF-8, `snake_case` field names |
| Auth | Session cookie `eos_session` (signed, `HttpOnly`, `SameSite=Lax`). Every endpoint needs it except `GET /auth/users`, `POST /auth/login`, `GET /healthz` |
| Writes | Every `POST`, `PUT`, `PATCH`, `DELETE` needs `Content-Type: application/json` and `X-EOS-CSRF: 1`. A write with no body sends `{}`. A browser `Origin`, if present, must be the web origin (plan 3.15) |
| Request id | Every response carries `X-Request-ID` (generated, or propagated from the Next.js server). Errors repeat it in the body |
| Instants | ISO 8601 in UTC with `Z`, for example `2026-11-09T16:00:00Z` |
| Calendar dates | `YYYY-MM-DD` in company time (`America/Chicago`): `due_date`, `week_start`, `today`. Weeks are named by their Monday |
| Decimals | Scores and goals are returned as **strings** in their shortest exact form, with no trailing zeros and no exponent (`"3"`, `"4.5"`, `"12.25"`, `"100"`), so no client ever does float maths. The server formats them with `app.jsonutil.decimal_str` (the database stores `numeric(14,4)`, so `8.0000` is sent as `"8"`). Requests accept a string or a number, at most 4 decimal places, absolute value up to 1e9. Meeting ratings are the exception: a JSON number with one decimal (`8.3`, `8.0`) |
| Computed values | Statuses, overdue flags, completion rates, Rock status and progress, Issue order and ratings are always computed by the server (rules module). Clients display them, never recompute them |
| Ids | Seed ids are kept (`u1`, `m1`, `t12`, `mt1`). New rows get a prefixed random id, for example `i_7k3m9q2x`. Path ids must match `^[a-z0-9_]{1,64}$` |
| Unknown fields | Rejected with `422` (`extra="forbid"`) |
| Lists | No pagination: the data set is one company. Documented as a known limitation. The one exception is the activity log (bonus), which uses keyset pagination because it grows without bound |
| Compression | Responses over 1 KB are gzipped when the client accepts it; SSE is never compressed |
| Caching | Authenticated responses send `Cache-Control: no-store` |

### Error envelope

Every error, whatever the status, has the same shape:

```json
{
  "error": {
    "code": "forbidden",
    "message": "You do not have access to this team.",
    "details": null,
    "request_id": "req_9f2c41d8"
  }
}
```

| Status | `code` | When |
|---|---|---|
| 400 | `bad_request` | Malformed JSON |
| 401 | `unauthenticated` | No, expired or tampered session cookie |
| 401 | `invalid_login` | Login with an unknown user id |
| 401 | `signature_invalid` | Only with the signing bonus (plan 3.16) |
| 403 | `forbidden` | Signed in, but no access to this team, or the role can't write (Observer) |
| 403 | `csrf_failed` | Write without `X-EOS-CSRF`, or with a foreign `Origin` |
| 403 | `not_facilitator` | Advancing or ending a meeting you don't facilitate |
| 403 | `not_attendee` | Rating a meeting you haven't joined |
| 404 | `not_found` | Unknown id (in a team you can access) |
| 409 | `meeting_already_active` | Starting a meeting while one is active; `details.meeting_id` names it |
| 409 | `meeting_ended` | Acting on a meeting that has ended |
| 409 | `meeting_not_ended` | Asking for the summary of an active meeting |
| 409 | `section_changed` | `advance` sent with a stale `expected_section` |
| 409 | `last_section` | `advance` while already in Conclude (end it instead) |
| 409 | `already_solved` | Solving a solved Issue |
| 409 | `stale_version` | Only with the lost-update bonus: `If-Match` no longer matches; `details.current` holds the current row |
| 413 | `payload_too_large` | Body over 64 KB |
| 415 | `unsupported_media_type` | Write that isn't `application/json` |
| 422 | `validation_failed` | Field errors; `details.fields` is a list of `{loc, msg}` |
| 422 | `cell_not_off_track` | Make it an Issue on a cell that isn't off track (and has no open Issue) |
| 422 | `owner_not_eligible` | Owner is an Observer, or not an Admin or member of the team |
| 422 | `week_out_of_range` | Week isn't a Monday inside the 13 shown weeks |
| 429 | `rate_limited` | Over a rate limit; `Retry-After` header set |
| 500 | `internal_error` | Unexpected error; details only in the logs, found by `request_id` |
| 503 | `db_busy` | No database connection free within 5 s |
| 503 | `activity_unavailable` | Only with the activity log bonus: the activity worker is down; the rest of the API keeps working |

Generic codes, used when no specific code above applies: `method_not_allowed` (405, with an `Allow` header), `conflict` (409), `service_unavailable` (503), and `error` for any other status.

Validation example (`priority: 9`):

```json
{
  "error": {
    "code": "validation_failed",
    "message": "Request validation failed.",
    "details": { "fields": [ { "loc": ["body", "priority"], "msg": "Input should be less than or equal to 5" } ] },
    "request_id": "req_51ab07e3"
  }
}
```

### Access levels used below

| Level | Who |
|---|---|
| Public | Anyone, no session |
| Signed in | Any valid session |
| Team read | Admin, or a member of the team (any role) |
| Team write | Admin, or a Team Member of the team (not Observer) |
| Facilitator | The meeting's facilitator |
| Rater | A joined attendee who is an Admin or Team Member |

Access is checked before anything else, including the cache (plan 3.14). An inaccessible team gives `403`, even for a guessed id.

## 2. Endpoints at a glance

| Method and path | Access | Success | Notable errors |
|---|---|---|---|
| `GET /auth/users` | Public | 200 | |
| `POST /auth/login` | Public | 200 + cookie | 401 `invalid_login`, 429 |
| `POST /auth/logout` | Signed in | 204 | |
| `GET /me` | Signed in | 200 | 401 |
| `GET /teams` | Signed in | 200 | |
| `GET /teams/{team_id}` | Team read | 200 | 403, 404 |
| `GET /teams/{team_id}/scorecard` | Team read | 200 | 403 |
| `PUT /teams/{team_id}/measurables/{measurable_id}/scores/{week_start}` | Team write | 200 | 403, 404, 422 |
| `DELETE /teams/{team_id}/measurables/{measurable_id}/scores/{week_start}` | Team write | 204 | 403, 404, 422 |
| `POST /teams/{team_id}/measurables/{measurable_id}/scores/{week_start}/issue` | Team write | 201 created, 200 existing | 403, 422 `cell_not_off_track`, 429 |
| `GET /teams/{team_id}/issues?status=unsolved\|solved` | Team read | 200 | 403 |
| `POST /teams/{team_id}/issues` | Team write | 201 | 403, 422 |
| `PATCH /issues/{issue_id}` | Team write | 200 | 403, 404, 409 `already_solved`, 422 |
| `POST /issues/{issue_id}/solve` | Team write | 200 | 403, 404, 409 `already_solved`, 422 |
| `POST /issues/{issue_id}/todos` | Team write | 201 | 403, 404, 422 `owner_not_eligible` |
| `GET /teams/{team_id}/todos` | Team read | 200 | 403 |
| `PUT /todos/{todo_id}/done` | Team write | 200 | 403, 404 |
| `GET /teams/{team_id}/rocks` | Team read | 200 | 403 |
| `GET /teams/{team_id}/meetings/active` | Team read | 200 | 403 |
| `POST /teams/{team_id}/meetings` | Team write | 201 | 403, 409 `meeting_already_active` |
| `GET /meetings/{meeting_id}` | Team read | 200 | 403, 404 |
| `POST /meetings/{meeting_id}/join` | Team read | 200 | 403, 404, 409 `meeting_ended` |
| `POST /meetings/{meeting_id}/advance` | Facilitator | 200 | 403 `not_facilitator`, 409 `section_changed`, `last_section`, `meeting_ended` |
| `POST /meetings/{meeting_id}/end` | Facilitator | 200 | 403 `not_facilitator`, 409 `meeting_ended` |
| `PUT /meetings/{meeting_id}/rating` | Rater | 200 | 403 `not_attendee`, 409 `meeting_ended`, 422 |
| `GET /meetings/{meeting_id}/summary` | Team read | 200 | 403, 404, 409 `meeting_not_ended` |
| `GET /teams/{team_id}/events` | Team read | 200 SSE stream | 403, 429 (more than 5 streams) |
| `GET /activity` (bonus) | Admin | 200 | 403, 422, 503 `activity_unavailable` |
| `GET /healthz` (root, not under `/api/v1`) | Public | 200 | 503 if the database is unreachable |
| `GET /api/v1/ping` | Public | 200 `{"pong": "ok"}` | Round-trip check through the web proxy (`http://localhost:3000/api/v1/ping`) |

## 3. Session

### `GET /auth/users`

The seeded user list for the login switcher.

```json
[
  { "id": "u1", "name": "Avery Admin", "email": "avery@acme.test", "role": "admin", "teams": [ { "id": "team_lead", "name": "Leadership" } ] },
  { "id": "u2", "name": "Blake Brooks", "email": "blake@acme.test", "role": "team_member", "teams": [ { "id": "team_lead", "name": "Leadership" }, { "id": "team_sales", "name": "Sales" } ] }
]
```

(9 users in total.) `teams` lists memberships; Admins can still access every team.

### `POST /auth/login`

Request `{ "user_id": "u3" }`. Response `200` with `Set-Cookie: eos_session=…; HttpOnly; SameSite=Lax; Path=/; Max-Age=43200` and the same body as `GET /me`. Unknown id: `401 invalid_login`.

### `POST /auth/logout`

Request `{}`. Response `204`, cookie cleared.

### `GET /me`

Everything the UI needs to render without doing time-zone maths itself. Example for `u3`:

```json
{
  "user": { "id": "u3", "name": "Casey Cho", "email": "casey@acme.test", "role": "team_member" },
  "teams": [ { "id": "team_lead", "name": "Leadership", "can_write": true } ],
  "company": { "id": "co_1", "name": "Acme Logistics", "timezone": "America/Chicago" },
  "clock": {
    "now": "2026-11-11T15:00:00Z",
    "today": "2026-11-11",
    "current_week": "2026-11-09",
    "last_closed_week": "2026-11-02"
  }
}
```

For an Admin, `teams` lists every team. `can_write` is a display hint; the server re-checks every write.

## 4. Teams

### `GET /teams`

```json
[ { "id": "team_lead", "name": "Leadership", "active_meeting_id": null } ]
```

### `GET /teams/{team_id}`

```json
{
  "id": "team_lead",
  "name": "Leadership",
  "members": [
    { "id": "u1", "name": "Avery Admin", "role": "admin" },
    { "id": "u5", "name": "Ellis Evans", "role": "observer" }
  ],
  "eligible_owners": [
    { "id": "u1", "name": "Avery Admin" },
    { "id": "u2", "name": "Blake Brooks" },
    { "id": "u3", "name": "Casey Cho" },
    { "id": "u4", "name": "Dana Diaz" }
  ],
  "active_meeting": null
}
```

(`members` shortened; Leadership has `u1` to `u5`.) `eligible_owners` = non-Observer members plus every Admin (decision 5). For Sales it would be `u1`, `u2`, `u6`.

## 5. Scorecard

### `GET /teams/{team_id}/scorecard`

13 weeks, oldest first, ending with the current week.

```json
{
  "weeks": ["2026-08-17", "…", "2026-11-02", "2026-11-09"],
  "current_week": "2026-11-09",
  "last_closed_week": "2026-11-02",
  "measurables": [
    {
      "id": "m1",
      "name": "New deals closed",
      "unit": "count",
      "owner": { "id": "u2", "name": "Blake Brooks" },
      "goal": { "type": "at_least", "value": "10" },
      "cells": [
        { "week_start": "2026-10-26", "value": "9", "status": "off_track", "version": 1, "open_issue_id": null },
        { "week_start": "2026-11-02", "value": "8", "status": "off_track", "version": 1, "open_issue_id": "i5" },
        { "week_start": "2026-11-09", "value": null, "status": "pending", "version": null, "open_issue_id": null }
      ]
    }
  ]
}
```

(`cells` always has all 13 weeks; shortened here.) `goal` is `{type, value}` or, for `between`, `{type, min, max}`. `open_issue_id` lets the UI show a link to the existing Issue instead of the *Make it an Issue* button.

### `PUT …/measurables/{measurable_id}/scores/{week_start}`

Request `{ "value": "11" }` (or `11`). Response `200` with the updated cell (new `value`, recomputed `status`, `version`). Last save wins. With the lost-update bonus, an optional `If-Match: "<version>"` header gives `409 stale_version` when out of date.

### `DELETE …/measurables/{measurable_id}/scores/{week_start}`

Clears the score; the cell becomes `off_track` (closed week) or `pending` (current week). Response `204`.

### `POST …/measurables/{measurable_id}/scores/{week_start}/issue` (Make it an Issue)

Request `{}`. If an unsolved Issue already links to this Measurable and week, it is returned with `200`; otherwise the cell must be off track and a new Issue is created with `201`. Concurrent clicks always end in exactly one Issue (plan 3.8).

Seed example, `m1` week `2026-11-02` (already has `i5`): `200`

```json
{
  "created": false,
  "issue": {
    "id": "i5",
    "title": "New deals closed, week of Nov 2",
    "owner": { "id": "u2", "name": "Blake Brooks" },
    "priority": 4,
    "created_at": "2026-11-09T16:00:00Z",
    "solved_at": null,
    "resolution_note": null,
    "source": { "kind": "measurable_week", "measurable_id": "m1", "measurable_name": "New deals closed", "week_start": "2026-11-02" },
    "todo_count": 0,
    "version": 1
  }
}
```

`m1` week `2026-10-26` (off track, no Issue yet) gives `201` with `"created": true`, a new id, title `New deals closed, week of Oct 26`, owner = the caller, priority `null`. `m1` week `2026-09-07` (score 10, on track) gives `422 cell_not_off_track`.

## 6. Issues

### `GET /teams/{team_id}/issues?status=unsolved`

Unsolved Issues in Issue order (priority 5 to 1, oldest first within a priority, no priority last). Leadership at the seed: `i2, i1, i5, i3, i4`. Each item has the shape shown under *Make it an Issue*.

`?status=solved` returns solved Issues, newest `solved_at` first, with `solved_at` and `resolution_note` set. Leadership at the seed: `i6, i7`.

### `POST /teams/{team_id}/issues`

Request `{ "title": "Trucks idle on Mondays", "priority": 3 }` (`priority` optional, 1 to 5). Response `201` with the Issue; owner = the caller, `source: null`.

### `PATCH /issues/{issue_id}`

Request `{ "priority": 5 }` or `{ "priority": null }`. Response `200` with the Issue. Optional `If-Match` with the lost-update bonus.

### `POST /issues/{issue_id}/solve`

Request `{ "resolution_note": "Switched carrier pickup to 7 AM." }` (required, 1 to 2000 characters after trimming). Response `200` with the Issue, `solved_at` set to now. Already solved: `409 already_solved`.

### `POST /issues/{issue_id}/todos`

Request `{ "title": "Call carrier about pickup window", "owner_id": "u8" }`. Response `201` with the To-Do: `due_date` = today in company time + 7 days, `source_issue` set. Owner not eligible for the Issue's team: `422 owner_not_eligible`.

## 7. To-Dos

### `GET /teams/{team_id}/todos`

Open To-Dos first (by due date), then done ones (newest first), plus last closed week's completion rate.

```json
{
  "items": [
    {
      "id": "t12",
      "title": "Publish hiring ad",
      "owner": { "id": "u3", "name": "Casey Cho" },
      "due_date": "2026-11-01",
      "done_at": null,
      "overdue": true,
      "source_issue": null,
      "created_at": "2026-10-25T21:00:00Z"
    }
  ],
  "last_closed_week_completion": {
    "week_start": "2026-11-02",
    "due": 10,
    "done": 9,
    "rate_percent": 90,
    "meets_target": true
  }
}
```

Leadership at the seed: overdue = `t12`, `t31`; `t30` (due today) is not overdue. `last_closed_week_completion` is `null` when nothing was due that week.

### `PUT /todos/{todo_id}/done`

Request `{ "done": true }` sets `done_at` to now; `{ "done": false }` clears it. Idempotent: marking a done To-Do done again keeps its original `done_at`. Response `200` with the To-Do.

## 8. Rocks

### `GET /teams/{team_id}/rocks`

Current quarter only; read-only.

```json
{
  "quarter": "2026-Q4",
  "items": [
    {
      "id": "r2",
      "title": "Hire VP of Sales",
      "owner": { "id": "u3", "name": "Casey Cho" },
      "seeded_status": "on_track",
      "status": "off_track",
      "progress_percent": 13,
      "milestones": [
        { "id": "ms4", "title": "Job description approved", "due_date": "2026-10-10", "done": true, "past_due": false },
        { "id": "ms5", "title": "Shortlist of 5", "due_date": "2026-11-10", "done": false, "past_due": true }
      ]
    }
  ]
}
```

(`r2` has 8 Milestones; shortened.) `status` follows the brief's rule, so `r2` is off track because `ms5` is past due, even though it was seeded on track.

## 9. Meetings

### Meeting state object

Returned by every meeting endpoint and pushed as the `meeting.state` event.

```json
{
  "id": "mt_4q8z1c7d",
  "team_id": "team_lead",
  "status": "active",
  "section": "ids",
  "section_started_at": "2026-11-11T15:06:10Z",
  "section_duration_s": 3600,
  "server_now": "2026-11-11T15:20:00Z",
  "started_at": "2026-11-11T15:00:30Z",
  "ended_at": null,
  "scorecard_week": "2026-11-02",
  "facilitator": { "id": "u1", "name": "Avery Admin" },
  "attendees": [
    { "id": "u1", "name": "Avery Admin", "role": "admin", "joined_at": "2026-11-11T15:00:30Z" },
    { "id": "u3", "name": "Casey Cho", "role": "team_member", "joined_at": "2026-11-11T15:01:02Z" }
  ],
  "ratings": [],
  "average_rating": null
}
```

Durations: Scorecard 300 s, IDS 3600 s, Conclude 600 s. Remaining time = `section_duration_s - (server_now - section_started_at)`; negative means over time. Nothing advances on its own.

### `GET /teams/{team_id}/meetings/active`

`200` with `{ "meeting": <state> }` or `{ "meeting": null }`.

### `POST /teams/{team_id}/meetings` (start)

Request `{}`. The caller becomes facilitator and first attendee; section `scorecard`. Response `201` with the state. Already active: `409 meeting_already_active` with `details.meeting_id`.

### `POST /meetings/{meeting_id}/join`

Request `{}`. Idempotent. Anyone with team read access, Observers included. Response `200` with the state.

### `POST /meetings/{meeting_id}/advance`

Request `{ "expected_section": "scorecard" }`. Moves forward one section (Scorecard to IDS to Conclude) only if the meeting is still in `expected_section`, so a double click can't skip a section. Response `200` with the new state. Errors: `409 section_changed`, `409 last_section`, `403 not_facilitator`.

### `POST /meetings/{meeting_id}/end`

Request `{}`. Allowed from any section. Freezes the summary snapshot in the same transaction. Response `200` with the final state (`status: "ended"`).

### `PUT /meetings/{meeting_id}/rating`

Request `{ "rating": 8 }` (1 to 10). Upsert; can change until the meeting ends. Response `200` with `{ "user_id": "u3", "rating": 8 }`. Observers get `403 forbidden`; non-attendees `403 not_attendee`.

### `GET /meetings/{meeting_id}/summary`

The frozen snapshot (plan 3.9), never recomputed. Its core fields match the rules report's meeting format; `labels` adds the names the UI shows. Seeded `mt2`:

```json
{
  "meeting_id": "mt2",
  "team_id": "team_lead",
  "facilitator_id": "u2",
  "started_at": "2026-11-04T15:00:00Z",
  "ended_at": "2026-11-04T16:20:00Z",
  "scorecard_week": "2026-10-26",
  "measurable_status": { "m1": "off_track", "m2": "on_track", "m3": "on_track", "m4": "off_track", "m5": "on_track" },
  "issues_solved": ["i6"],
  "todos_created": ["t30"],
  "attendee_ids": ["u1", "u2", "u3", "u4", "u5"],
  "rating": 8.3,
  "labels": {
    "users": { "u1": "Avery Admin", "u2": "Blake Brooks", "u3": "Casey Cho", "u4": "Dana Diaz", "u5": "Ellis Evans" },
    "measurables": { "m1": "New deals closed", "m2": "Customer churn", "m3": "Avg first response", "m4": "Payroll runs", "m5": "Cash on hand" },
    "issues": { "i6": "Payroll runs, week of Oct 26" },
    "todos": { "t30": "Set payroll reminder" }
  }
}
```

`rating` is a number with one decimal (half up), or `null` if nobody rated. An active meeting gives `409 meeting_not_ended`.

## 10. Live updates: `GET /teams/{team_id}/events`

Server-Sent Events (`text/event-stream`), one stream per team for the Team and Meeting pages. Never gzipped. At most 5 open streams per user. Events are hints: clients re-read data through the REST endpoints above (or re-render on the server, plan 3.17), so an event never carries data a user couldn't fetch.

```
retry: 2000

event: snapshot
id: 41
data: {"team_id":"team_lead","cache_version":41,"active_meeting":null}

event: team.changed
id: 42
data: {"team_id":"team_lead","entity":"issues","ids":["i5"],"cache_version":42}

event: meeting.state
id: 43
data: { …meeting state object… }

event: meeting.ended
id: 44
data: {"meeting_id":"mt_4q8z1c7d"}

: ping
```

| Event | When | Payload |
|---|---|---|
| `snapshot` | On every (re)connect | `team_id`, `cache_version`, `active_meeting` (state or `null`) |
| `team.changed` | Any team-scoped write | `entity` (`scores`, `issues`, `todos`, `meeting`), affected `ids`, `cache_version` |
| `meeting.state` | Start, join, advance, rating | The meeting state object |
| `meeting.ended` | End | `meeting_id` |
| `: ping` (comment) | Every 15 s | Keeps proxies from closing the stream |

The event `id` is the team's `cache_version`, which only goes up. On reconnect the browser sends `Last-Event-ID`; the server always answers with a fresh `snapshot`, and clients refresh once.

## 11. Health: `GET /healthz`

```json
{
  "status": "ok",
  "db": "ok",
  "redis": "ok",
  "pool": { "size": 5, "open": 2, "checked_out": 1, "overflow": 0 },
  "cache": { "hits": 1204, "misses": 87 },
  "activity_backlog": { "rows": 0, "oldest_age_s": 0 },
  "version": "1.0.0"
}
```

`status` is `degraded` (still HTTP 200) when Redis is down, because the app works without it, and, with the activity log bonus, when the oldest outbox row is more than 5 minutes old. A database failure gives HTTP 503.

## 11a. Activity log (bonus): `GET /activity`

Admins only (plan 3.18). The main API checks access, then forwards the query to the activity worker; it never touches the activity database itself. Newest first, keyset-paginated.

| Query parameter | Meaning |
|---|---|
| `q` | Full-text search over summaries and before/after values, `websearch` syntax: `"carrier pickup"`, `pickup -delay`, `priority OR solved`. Max 200 characters |
| `team_id` | One team; `none` for company-level events only |
| `table` | A main-database table name, or `app` for app events |
| `op` | `insert`, `update`, `delete`, `truncate`, `event` |
| `actor_id` | A user id, or `system` |
| `source` | `app`, `seed`, `system` |
| `from`, `to` | Calendar dates in company time, inclusive |
| `row_id` | Exact row id, for the full history of one record |
| `request_id` | Everything one request changed |
| `meeting_id` | Everything changed during one meeting |
| `before` | Event id cursor from the previous page's `next_before` |
| `limit` | 1 to 100, default 50 |

All filters combine with AND. Unknown parameters or bad values give `422`.

```json
{
  "items": [
    {
      "id": 1043,
      "occurred_at": "2026-11-11T16:02:11Z",
      "txid": 88231,
      "source": "app",
      "team": { "id": "team_ops", "name": "Operations" },
      "actor": { "id": "u8", "name": "Harper Hill" },
      "table": "issues",
      "op": "update",
      "row_id": "i9",
      "action": "solved",
      "summary": "Harper Hill solved Issue \"Carrier pickup delays\"",
      "summary_highlighted": "Harper Hill solved Issue \"<mark>Carrier pickup</mark> delays\"",
      "changes": [
        { "field": "solved_at", "old": null, "new": "2026-11-11T16:02:11Z" },
        { "field": "resolution_note", "old": null, "new": "Switched carrier pickup to 7 AM." }
      ],
      "before": { "id": "i9", "title": "Carrier pickup delays", "priority": 2, "solved_at": null, "resolution_note": null },
      "after": { "id": "i9", "title": "Carrier pickup delays", "priority": 2, "solved_at": "2026-11-11T16:02:11Z", "resolution_note": "Switched carrier pickup to 7 AM." },
      "request_id": "req_51ab07e3",
      "meeting_id": null
    }
  ],
  "next_before": 1042
}
```

(`before` and `after` are full row snapshots; shortened here.) `summary_highlighted` is present only when `q` is set: it is server-escaped HTML in which only `<mark>` tags are allowed. `next_before` is `null` on the last page. Events sharing a `txid` changed together in one transaction; the Admin page groups them like a git commit.

## 12. OpenAPI and the typed client

- Every route declares `response_model`, request examples (the ones above) and its error responses, so `/docs` shows the envelope for every status.
- Tags per area (Session, Teams, Scorecard, Issues, To-Dos, Rocks, Meetings, Live, Health).
- Stable `operationId`s from route function names (`get_scorecard`, `make_issue`, …), so the generated TypeScript client has readable names.
- The committed `openapi.json` is regenerated and compared in the test suite (plan 3.17).
