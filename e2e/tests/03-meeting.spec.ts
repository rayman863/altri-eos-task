import { currentSection, DEMO_FAILURE, expect, test } from "./helpers";

/**
 * The brief's core journey with two browsers in the same meeting: the facilitator starts
 * it, a teammate joins from their own browser, both follow every section change live,
 * a reload restores the current section, the teammate rates, the facilitator ends it, and
 * both land on the summary.
 *
 * Set E2E_DEMO_FAILURE=trace-demo to break it on purpose: the teammate's live stream is blocked, so
 * their page stops following the meeting and the test fails with a trace (that's how
 * artifacts/e2e-failure-trace.zip was made).
 */
test("two browsers follow one meeting from start to summary", async ({ signIn }) => {
  const casey = await signIn("Casey"); // facilitator
  const blake = await signIn("Blake"); // teammate in a second browser
  if (DEMO_FAILURE) {
    console.warn("E2E_DEMO_FAILURE=trace-demo: blocking the teammate's live stream, so this test fails on purpose.");
    await blake.route("**/api/v1/teams/*/events", (route) => route.abort());
  }

  // Casey starts the meeting and becomes its facilitator.
  await casey.goto("/teams/team_lead/meeting");
  await casey.getByRole("button", { name: "Start meeting" }).click();
  await expect(currentSection(casey)).toContainText("Scorecard");
  await expect(casey.getByRole("button", { name: "Next section" })).toBeVisible();

  // Blake opens the meeting page and joins automatically; Casey sees him arrive live.
  await blake.goto("/teams/team_lead/meeting");
  await expect(currentSection(blake)).toContainText("Scorecard");
  await expect(blake.getByText("The facilitator moves the meeting along")).toBeVisible();
  await expect(blake.getByRole("button", { name: "Next section" })).toHaveCount(0);
  await expect(casey.getByLabel("Attendees").getByText("Blake Brooks")).toBeVisible();

  // Scorecard -> IDS: Blake follows within about two seconds, without reloading.
  await casey.getByRole("button", { name: "Next section" }).click();
  await expect(currentSection(casey)).toContainText("IDS");
  await expect(currentSection(blake)).toContainText("IDS", { timeout: 2_000 });
  await expect(blake.getByRole("heading", { name: "IDS: Identify, Discuss, Solve" })).toBeVisible();

  // A reload in the middle of the meeting lands on the current section.
  await blake.reload();
  await expect(currentSection(blake)).toContainText("IDS");

  // IDS -> Conclude, then Blake rates the meeting.
  await casey.getByRole("button", { name: "Next section" }).click();
  await expect(currentSection(blake)).toContainText("Conclude", { timeout: 2_000 });
  await blake.getByRole("radio", { name: "8", exact: true }).click();
  await expect(blake.getByText("Your rating: 8")).toBeVisible();
  await expect(casey.getByText(/1 of 2 rated/)).toBeVisible();

  // Casey ends it (with confirmation); both browsers land on the frozen summary.
  await casey.getByRole("button", { name: "End meeting" }).click();
  await casey.getByRole("alertdialog").getByRole("button", { name: "End meeting" }).click();
  await expect(casey).toHaveURL(/\/meetings\/mt_[a-z0-9]+\/summary$/);
  await expect(blake).toHaveURL(/\/meetings\/mt_[a-z0-9]+\/summary$/);
  await expect(blake.getByRole("heading", { name: "Level 10 Meeting summary" })).toBeVisible();
  await expect(blake.getByText("8.0", { exact: true })).toBeVisible();
  await expect(blake.getByText("Blake Brooks, Casey Cho")).toBeVisible(); // attendees by id

  // Back on the team page, Past meetings lists it first, ahead of the two seeded ones, and
  // links back to the same summary.
  const summaryUrl = blake.url();
  await blake.getByRole("link", { name: "Back to the team" }).click();
  const past = blake.getByRole("region", { name: "Past meetings" }).getByRole("link");
  await expect(past).toHaveCount(3);
  await expect(past.first()).toContainText("Facilitated by Casey Cho · 2 attendees");
  await expect(past.first()).toContainText("8.0");
  await past.first().click();
  await expect(blake).toHaveURL(summaryUrl);
});
