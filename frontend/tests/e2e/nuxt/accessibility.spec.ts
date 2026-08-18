import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";

const wcag21AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(wcag21AA).analyze();
  expect(results.violations).toEqual([]);
}

test("the hydrated Nuxt explorer and open native controls pass WCAG checks @a11y", async ({
  page,
}) => {
  await mockNuxtExternalServices(page);
  await page.goto("./");
  await expect(page.locator(".civic-dashboard-browser-explorer")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await expect(page.locator(".maplibregl-canvas")).toHaveAttribute(
    "aria-label",
    /shooting-victim locations/,
  );
  await expectNoAxeViolations(page);

  const sidebar = page.getByRole("complementary", {
    name: "Map filters and controls",
  });
  await page.getByRole("button", { name: "About Outcome" }).click();
  await sidebar.locator("details", { hasText: "Gender" }).locator("summary").click();
  await sidebar.getByRole("button", { name: "Download Data" }).click();
  await expect(page.getByRole("dialog", { name: "Download Data" })).toBeVisible();
  await expectNoAxeViolations(page);
});

test("the reference pages pass WCAG checks @a11y", async ({ page }) => {
  await mockNuxtExternalServices(page);

  for (const referencePage of ["stats", "data", "methodology", "about"]) {
    await test.step(referencePage, async () => {
      await page.goto(`./${referencePage}`);
      await expect(page.locator("main.civic-reference-page h1")).toBeVisible();
      await expectNoAxeViolations(page);
    });
  }
});

test("announces SPA routes once and moves focus only after navigation @a11y", async ({
  page,
}) => {
  await mockNuxtExternalServices(page);
  await page.goto("./data");

  const main = page.locator("#main-content");
  const announcer = page.locator(".nuxt-route-announcer");
  await expect(main).toBeVisible();
  await expect(main).not.toBeFocused();
  await expect(announcer).toHaveCount(1);
  await expect(announcer.getByRole("status")).not.toBeEmpty();

  const statisticsLink = page
    .getByRole("navigation", { name: "Primary navigation" })
    .getByRole("link", { name: "Statistics" });
  await statisticsLink.focus();
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/stats$/);
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Philadelphia shooting-victim and homicide statistics",
    }),
  ).toBeVisible();
  await expect(page.locator("#main-content")).toBeFocused();
  await expect(announcer).toHaveCount(1);
  await expect(announcer.getByRole("status")).toContainText(
    "Philadelphia gun violence statistics, 2026",
  );
});
