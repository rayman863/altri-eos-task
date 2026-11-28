import { test as base, type BrowserContext, expect, type Page } from "@playwright/test";

/**
 * `signIn("Casey")` gives a signed-in page for one seeded user, through the real login
 * page. Each call opens its own browser context, so two calls are two separate browsers
 * with separate cookies. The fixture closes every context it opened when the test ends,
 * so no live stream or page survives into the next test.
 */
export const test = base.extend<{ signIn: (firstName: string) => Promise<Page> }>({
  signIn: async ({ browser }, use) => {
    const contexts: BrowserContext[] = [];
    // Content-Security-Policy violations on any page of any of these browsers (layer L4):
    // a test passes only if none happened, so every flow also proves the policy blocks
    // nothing the app itself renders.
    const violations: string[] = [];
    await use(async (firstName: string) => {
      const context = await browser.newContext();
      contexts.push(context);
      await context.exposeFunction("__reportCsp", (v: string) => violations.push(v));
      await context.addInitScript(() => {
        document.addEventListener("securitypolicyviolation", (e) =>
          (window as unknown as { __reportCsp: (v: string) => void }).__reportCsp(
            `${e.violatedDirective} ${e.blockedURI} on ${location.pathname}`,
          ),
        );
      });
      const page = await context.newPage();
      await page.goto("/login");
      await page.getByRole("button", { name: `Sign in as ${firstName}` }).click();
      await expect(page).toHaveURL(/\/teams\//);
      return page;
    });
    await Promise.all(contexts.map((context) => context.close()));
    expect(violations, "Content-Security-Policy violations").toEqual([]);
  },
});

export { expect };

/** The value that makes the meeting test fail on purpose (artifacts/README.md). Any other
 * value, including "1", is ignored, so a stray variable can't break a real run. */
export const DEMO_FAILURE = process.env.E2E_DEMO_FAILURE === "trace-demo";

/** The Scorecard cell button for a Measurable and week, found by its accessible name,
 * which carries the value and status, e.g. "Customer churn, week of 2026-11-09: 3, On track". */
export function scoreCell(page: Page, measurable: string, week: string) {
  return page.getByRole("button", { name: new RegExp(`^${measurable}, week of ${week}:`) });
}

/** The agenda item the meeting is on (aria-current="step"). */
export function currentSection(page: Page) {
  return page.locator('[aria-label="Agenda"] [aria-current="step"]');
}
