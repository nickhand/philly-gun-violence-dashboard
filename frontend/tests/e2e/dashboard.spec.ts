import { expect, test } from "@playwright/test";
import { mockDashboardApi } from "./support/mockApi";

test.beforeEach(async ({ page }) => {
  await mockDashboardApi(page);
  await page.goto("./");
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Mapping Philadelphia's Gun Violence",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Map data summary" }),
  ).toContainText("4 shooting victims");
});

test("keeps record totals consistent while reporting missing map locations", async ({
  page,
}) => {
  await expect(page.getByText(/2 nonfatal and 2 fatal/)).toBeVisible();
  await expect(page.getByText("Showing locations for 3 shooting victims")).toBeVisible();
  await expect(
    page.getByText("Note: 1 victim not shown due to missing locations"),
  ).toBeVisible();

  const outcomeTable = page.getByRole("table", {
    name: "Outcome distribution breakdown",
  });
  await expect(
    outcomeTable.getByRole("row", { name: "Fatal 2 50%", exact: true }),
  ).toBeVisible();
  await expect(
    outcomeTable.getByRole("row", {
      name: "Nonfatal 2 50%",
      exact: true,
    }),
  ).toBeVisible();

  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);
});

test("filters records, announces the result, and resets the state", async ({
  page,
}) => {
  const fatalOnly = page.getByRole("checkbox", {
    name: "Fatal shootings only",
  });
  await fatalOnly.press("Space");
  await expect(fatalOnly).toBeChecked();

  await expect(page.getByRole("status")).toContainText("Showing 2 shooting victims");
  await expect(page.getByText(/0 nonfatal and 2 fatal/)).toBeVisible();
  await expect(page.getByText("Showing locations for 1 shooting victim")).toBeVisible();
  await expect(
    page.getByText("Note: 1 victim not shown due to missing locations"),
  ).toBeVisible();

  const resetAll = page.getByRole("button", { name: "Reset All Filters" });
  await expect(resetAll).toBeEnabled();
  await resetAll.click();

  await expect(page.getByText(/2 nonfatal and 2 fatal/)).toBeVisible();
  await expect(fatalOnly).not.toBeChecked();
});

test("exports all records even when the current view is filtered", async ({
  page,
}) => {
  await page
    .getByRole("checkbox", { name: "Fatal shootings only" })
    .check();
  await page.getByRole("button", { name: "Download Data" }).click();

  const dialog = page.getByRole("dialog", { name: "Download Data" });
  await expect(dialog).toContainText(
    "Export 2 records matching current filters",
  );
  await dialog.getByRole("button", { name: "All Data" }).click();
  await expect(dialog).toContainText("Export all 4 records");
  await dialog.getByRole("button", { name: "CSV" }).click();

  const downloadPromise = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download", exact: true }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(
    /^shootings-all-\d{4}-\d{2}-\d{2}\.csv$/,
  );

  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) {
    chunks.push(Buffer.from(chunk));
  }
  const csv = Buffer.concat(chunks).toString("utf8");
  expect(csv.trim().split("\n")).toHaveLength(5);
  expect(csv).toContain("2026-03");
});

test("skip links move keyboard focus and every focused target has an indicator", async ({
  page,
  browserName,
}) => {
  await page.locator("body").press("Home");
  await page.keyboard.press(browserName === "webkit" ? "Alt+Tab" : "Tab");

  const skipLink = page.getByRole("link", { name: "Skip to main content" });
  await expect(skipLink).toBeFocused();
  await expect(skipLink).toHaveCSS("outline-style", "solid");

  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
  await expect(page.locator("#main-content")).toHaveCSS(
    "outline-style",
    "solid",
  );
});
