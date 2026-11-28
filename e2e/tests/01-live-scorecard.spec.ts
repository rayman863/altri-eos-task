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
