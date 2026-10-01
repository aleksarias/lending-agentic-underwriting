import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const ROUTES = [
  "/",
  "/activity",
  "/decisions",
  "/progress",
  "/history",
  "/definitions",
  "/upcoming",
  "/models",
  "/performance",
  "/fairness",
  "/feed",
  "/data",
  "/features",
  "/agents",
  "/agents/lessons",
  "/approvals",
  "/rollouts",
  "/readiness",
  "/shadow",
  "/alerts",
  "/cost",
  "/settings",
];

async function check(page: Page, errors: string[]) {
  await expect(page.locator("main h1").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(errors, errors.join("\n")).toEqual([]);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "the page scrolls horizontally").toBeLessThanOrEqual(1);
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.help} (${v.nodes.length} element(s), e.g. ${v.nodes[0]?.target.join(" ")})`)).toEqual([]);
}

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`page error: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console error: ${m.text()}`);
  });
  return errors;
}

for (const route of ROUTES) {
  test(`${route} renders, does not scroll sideways, passes axe`, async ({ page }) => {
    const errors = collectErrors(page);
    await page.goto(route);
    await check(page, errors);
  });
}

test("a decision opens from the list", async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto("/decisions");
  await page.waitForLoadState("networkidle");
  await page.getByRole("link", { name: /^Decision for application / }).first().click();
  await expect(page).toHaveURL(/\/decisions\/dec-/);
  await check(page, errors);
});
