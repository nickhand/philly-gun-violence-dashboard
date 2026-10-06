import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mockDashboardApi } from "./support/mockApi";

const wcag21AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function expectNoAxeViolations(page: Page) {
  await expect
    .poll(
      async () =>
        (await new AxeBuilder({ page }).withTags(wcag21AA).analyze()).violations,
      {
        message:
          "Expected no automatically detectable WCAG 2.1 A/AA violations",
        timeout: 10_000,
      },
    )
    .toEqual([]);
}

test("dashboard has no automatically detectable WCAG 2.1 A/AA violations @a11y", async ({
  page,
}) => {
  await mockDashboardApi(page);
  await page.goto("./");
  await expect(
    page.getByRole("region", { name: "Map data summary" }),
  ).toContainText("4 shooting victims");
  await expect(page.getByRole("progressbar")).toHaveCount(0);

  await expectNoAxeViolations(page);
});

test("interactive filter and download states pass WCAG checks @a11y", async ({
  page,
}) => {
  await mockDashboardApi(page);
  await page.goto("./");
  await expect(
    page.getByRole("region", { name: "Map data summary" }),
  ).toContainText("4 shooting victims");
  await expect(page.getByRole("progressbar")).toHaveCount(0);

  await page.getByRole("button", { name: "Gender" }).click();
  await page.getByRole("button", { name: "Download Data" }).click();
  const dialog = page.getByRole("dialog", { name: "Download Data" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveCSS("opacity", "1");
  await expect(page.locator(".v-ripple__animation--visible")).toHaveCount(0);

  await expectNoAxeViolations(page);
});

test("about page has no automatically detectable WCAG 2.1 A/AA violations @a11y", async ({
  page,
}) => {
  await mockDashboardApi(page);
  await page.goto("about");
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Philadelphia Gun Violence Dashboard",
    }),
  ).toBeVisible();

  await expectNoAxeViolations(page);
});
