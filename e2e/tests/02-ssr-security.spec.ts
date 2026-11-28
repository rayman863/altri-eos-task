import { expect, scoreCell, test } from "./helpers";

test("the Team page arrives as server-rendered HTML with the Scorecard values in it", async ({ request }) => {
  // No browser and no JavaScript: just the HTML the Next.js server sends.
  const login = await request.post("/api/v1/auth/login", {
    headers: { "X-EOS-CSRF": "1" },
    data: { user_id: "u3" },
  });
  expect(login.ok()).toBeTruthy();
  const response = await request.get("/teams/team_lead");
  expect(response.status()).toBe(200);
  const html = await response.text();
  expect(html).toContain("New deals closed");
  // Value and status of a cell, computed by the API and rendered on the server.
  expect(html).toContain('aria-label="New deals closed, week of 2026-11-02: 8, Off track"');
  expect(html).toContain("90%");
});

test("user text is rendered as text, never as markup (XSS)", async ({ signIn }) => {
  const casey = await signIn("Casey");
  const payload = `<img src=x onerror="window.__xss=1"><script>window.__xss=2</script>`;
  await casey.getByPlaceholder("Add an Issue…").fill(payload);
  await casey.getByRole("button", { name: "Add" }).click();
  await expect(casey.getByText(payload).first()).toBeVisible();
  expect(await casey.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();

  // A second user loading the page fresh (server-rendered) is just as safe.
  const blake = await signIn("Blake");
  await blake.goto("/teams/team_lead");
  await expect(blake.getByText(payload).first()).toBeVisible();
  expect(await blake.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
});

test("an Observer sees the team read-only and can't open other teams", async ({ signIn }) => {
  const ellis = await signIn("Ellis");
  await expect(ellis.getByText("Observers can view this team")).toBeVisible();
  await expect(ellis.getByPlaceholder("Add an Issue…")).toHaveCount(0);
  await expect(scoreCell(ellis, "New deals closed", "2026-11-02")).toBeDisabled();
  await expect(ellis.getByRole("button", { name: "Solve" })).toHaveCount(0);

  await ellis.goto("/teams/team_sales");
  await expect(ellis.getByText("You don't have access to this team")).toBeVisible();
});
