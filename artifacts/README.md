# Test artifacts

## `e2e-failure-trace.zip`

A Playwright trace from a deliberately broken end-to-end run, kept to show what a failing
browser test leaves behind for debugging.

How it was made: the two-browser meeting test (`e2e/tests/03-meeting.spec.ts`) was run with
`E2E_DEMO_FAILURE=trace-demo` (any other value is ignored, so a stray variable can't break a real run), which blocks the teammate's live event stream. The facilitator moves
the meeting from Scorecard to IDS, but the teammate's page never hears about it, so the
assertion "the teammate follows to IDS within 2 seconds" fails:

```
Error: expect(locator).toContainText(expected) failed
Expected substring: "IDS"
Received string:    "Scorecard 5 min"
```

To open it, either drop the file on https://trace.playwright.dev (it runs in your browser
and uploads nothing), or run `npx playwright show-trace artifacts/e2e-failure-trace.zip`
from the `e2e/` folder. The trace shows every action and assertion, DOM snapshots of both
browsers, their console output, and the network log, where the blocked
`/api/v1/teams/team_lead/events` request for the second browser is visible.

To reproduce it in PowerShell:

```powershell
docker compose --profile e2e build e2e-seed web-e2e
$env:E2E_DEMO_FAILURE = "trace-demo"; docker compose run --rm e2e; Remove-Item Env:E2E_DEMO_FAILURE
docker compose --profile e2e stop api-e2e web-e2e
```

Or in bash:

```bash
docker compose --profile e2e build e2e-seed web-e2e
E2E_DEMO_FAILURE=trace-demo docker compose run --rm e2e
docker compose --profile e2e stop api-e2e web-e2e
```

The new trace lands in `e2e/test-results/`.
