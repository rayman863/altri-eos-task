import { expect, scoreCell, test } from "./helpers";

test("a score edited in one browser shows up in the other within about a second", async ({ signIn }) => {
  const casey = await signIn("Casey");
  const blake = await signIn("Blake");
  await blake.goto("/teams/team_lead");
  await expect(blake.getByRole("status")).toHaveText("Live");

  // Casey edits Customer churn for the current week inline: click, type, Enter.
  await scoreCell(casey, "Customer churn", "2026-11-09").click();
  const input = casey.getByLabel("Score for Customer churn, week of 2026-11-09");
  await input.fill("2.9");
  await input.press("Enter");
  await expect(scoreCell(casey, "Customer churn", "2026-11-09")).toHaveAccessibleName(/: 2\.9, On track$/);

  // Blake's page re-renders from the live event, with no reload.
  await expect(scoreCell(blake, "Customer churn", "2026-11-09")).toHaveAccessibleName(/: 2\.9, On track$/, {
    timeout: 2_000,
  });

  // An over-limit value is refused in place and never saved.
  await scoreCell(casey, "Customer churn", "2026-11-09").click();
  await casey.getByLabel("Score for Customer churn, week of 2026-11-09").fill("1.23456");
  await casey.getByLabel("Score for Customer churn, week of 2026-11-09").press("Enter");
  await expect(casey.getByRole("alert").filter({ hasText: "at most 4 decimals" })).toBeVisible();
});

test("Make it an Issue on an off-track cell links the cell to the new Issue", async ({ signIn }) => {
  const casey = await signIn("Casey");
  await casey.getByRole("button", { name: "Make it an Issue: New deals closed, week of 2026-10-26" }).click();
  await expect(casey.getByText("New deals closed, week of Oct 26").first()).toBeVisible();
  // The cell now links to the Issue instead of offering to create another one.
  await expect(casey.getByRole("button", { name: "Make it an Issue: New deals closed, week of 2026-10-26" })).toHaveCount(0);
});

test("a save based on a value someone else just changed is refused, not written over it", async ({ signIn }) => {
  const casey = await signIn("Casey");
  const blake = await signIn("Blake");
  await expect(casey.getByRole("status")).toHaveText("Live");
  const cell = "Avg first response";

  // Casey opens the cell (3.3) and starts typing...
  await scoreCell(casey, cell, "2026-10-26").click();
  const caseyInput = casey.getByLabel(`Score for ${cell}, week of 2026-10-26`);

  // ...while Blake saves it first, then another cell of the same row.
  for (const [week, value] of [["2026-10-26", "2.5"], ["2026-10-19", "2.2"]]) {
    await scoreCell(blake, cell, week).click();
    await blake.getByLabel(`Score for ${cell}, week of ${week}`).fill(value);
    await blake.getByLabel(`Score for ${cell}, week of ${week}`).press("Enter");
    await expect(scoreCell(blake, cell, week)).toHaveAccessibleName(new RegExp(`: ${value.replace(".", "\.")}, `));
  }
  // Casey's page has refreshed underneath her open box (the second cell shows it)...
  await expect(scoreCell(casey, cell, "2026-10-19")).toHaveAccessibleName(/: 2\.2, /, { timeout: 2_000 });

  // ...so her save carries the version she started from, and is refused instead of
  // silently replacing a value she never saw. Her page then shows Blake's value.
  await caseyInput.fill("3.9");
  await caseyInput.press("Enter");
  await expect(casey.getByRole("alert").filter({ hasText: "Someone else changed this score" })).toBeVisible();
  await expect(scoreCell(casey, cell, "2026-10-26")).toHaveAccessibleName(/: 2\.5, On track$/);
  await expect(scoreCell(blake, cell, "2026-10-26")).toHaveAccessibleName(/: 2\.5, On track$/);
});

test("opening a cell and leaving it unchanged never touches a newer value someone else saved", async ({ signIn }) => {
  const casey = await signIn("Casey");
  const blake = await signIn("Blake");
  await expect(casey.getByRole("status")).toHaveText("Live");
  const cell = "Payroll runs";

  // Casey opens the cell (1) but doesn't type...
  await scoreCell(casey, cell, "2026-10-19").click();
  await expect(casey.getByLabel(`Score for ${cell}, week of 2026-10-19`)).toBeFocused();

  // ...while Blake saves it, then another cell of the row, so Casey's page has refreshed.
  for (const [week, value] of [["2026-10-19", "2"], ["2026-10-12", "0"]]) {
    await scoreCell(blake, cell, week).click();
    await blake.getByLabel(`Score for ${cell}, week of ${week}`).fill(value);
    await blake.getByLabel(`Score for ${cell}, week of ${week}`).press("Enter");
    await expect(scoreCell(blake, cell, week)).toHaveAccessibleName(new RegExp(`: ${value}, `));
  }
  await expect(scoreCell(casey, cell, "2026-10-12")).toHaveAccessibleName(/: 0, /, { timeout: 2_000 });

  // Casey clicks away. She changed nothing, so nothing is saved: no conflict warning, and
  // Blake's value stays (before this was handled, the blur wrote her stale "1" back).
  await casey.getByRole("heading", { name: "Scorecard" }).click();
  await expect(scoreCell(casey, cell, "2026-10-19")).toHaveAccessibleName(/: 2, Off track$/);
  await expect(casey.getByRole("alert").filter({ hasText: "Someone else changed" })).toHaveCount(0);
  await expect(scoreCell(blake, cell, "2026-10-19")).toHaveAccessibleName(/: 2, Off track$/);
});

test("an overdue To-Do and an off-track Rock can each become one Issue", async ({ signIn }) => {
  const casey = await signIn("Casey");

  await casey.getByRole("button", { name: "Make it an Issue: Publish hiring ad" }).click();
  await expect(casey.getByText("From the To-Do: Publish hiring ad")).toBeVisible();
  await expect(casey.getByRole("button", { name: "Make it an Issue: Publish hiring ad" })).toHaveCount(0);

  await casey.getByRole("button", { name: "Make it an Issue: Refresh brand" }).click();
  await expect(casey.getByText("From the Rock: Refresh brand")).toBeVisible();
  await expect(casey.getByRole("button", { name: "Make it an Issue: Refresh brand" })).toHaveCount(0);

  // Each source now links to its Issue instead of offering a second one.
  await expect(casey.getByRole("link", { name: "Open Issue: Publish hiring ad" })).toBeVisible();
  await expect(casey.getByRole("link", { name: "Open Issue: Refresh brand" })).toBeVisible();
});
