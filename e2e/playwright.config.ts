import { defineConfig, devices } from "@playwright/test";

/**
 * Browser end-to-end tests (plan section 6). They run in the `e2e` compose service against
 * an isolated stack (api-e2e + web-e2e on the eos_test database, frozen clock), which is
 * reseeded before every run, so they never touch the demo data.
 *
 * The tests share one team's data (a meeting, new Issues), so they run one at a time.
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 5_000 },
  reporter: [["list"]],
  outputDir: "test-results",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    // A failing test keeps its full trace (DOM snapshots, network, console) for
    // `npx playwright show-trace`; the committed example is artifacts/e2e-failure-trace.zip.
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
