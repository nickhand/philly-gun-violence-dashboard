import { expect, test } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";

test("keeps current-page semantics on a trailing-slash route", async ({ page }) => {
  await mockNuxtExternalServices(page);
  await page.goto("./stats/");

  await expect(page).toHaveURL(/\/stats\/$/);
  await expect(
    page.getByRole("link", { name: "Statistics", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByRole("link", { name: "Explore", exact: true }),
  ).not.toHaveAttribute("aria-current");
});

test("keeps clearable select text clear of native forced-color controls", async ({
  page,
}) => {
  await mockNuxtExternalServices(page);
  await page.emulateMedia({ forcedColors: "active" });
  await page.goto("./?layers=zip-codes");

  const select = page.getByLabel("Choropleth Layer", { exact: true });
  const clear = page.getByRole("button", { name: "Clear Choropleth Layer" });
  await expect(select).toHaveValue("zip-codes");
  await expect(clear).toBeVisible();

  const styles = await select.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      appearance: style.appearance,
      paddingRight: Number.parseFloat(style.paddingRight),
    };
  });
  const [selectBox, clearBox] = await Promise.all([
    select.boundingBox(),
    clear.boundingBox(),
  ]);

  expect(styles.appearance).not.toBe("none");
  expect(styles.paddingRight).toBeGreaterThanOrEqual(64);
  expect(selectBox).not.toBeNull();
  expect(clearBox).not.toBeNull();
  expect(clearBox!.x).toBeGreaterThan(selectBox!.x);
  expect(clearBox!.x + clearBox!.width).toBeLessThan(
    selectBox!.x + selectBox!.width,
  );
});
