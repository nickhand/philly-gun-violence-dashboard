import { expect, test } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";

test.use({ viewport: { height: 900, width: 1280 } });

test("inverse controls use the production hover treatment", async ({
  page,
}) => {
  await mockNuxtExternalServices(page);
  await page.goto("./");

  const year = page.getByLabel("Viewing data for");
  await expect(year).toBeVisible();
  await expect(year).toHaveCSS("background-color", "rgb(53, 61, 66)");
  await year.hover();
  await expect(year).toHaveCSS(
    "background-color",
    "rgba(255, 255, 255, 0.04)",
  );

  const boundary = page.getByLabel("Choropleth Layer");
  await boundary.scrollIntoViewIfNeeded();
  await expect(boundary).toHaveCSS(
    "border-color",
    "rgba(255, 255, 255, 0.38)",
  );
  await expect(boundary).toHaveCSS("background-color", "rgb(53, 61, 66)");
  await boundary.hover();
  await expect(boundary).toHaveCSS(
    "border-color",
    "rgba(255, 255, 255, 0.9)",
  );
  await expect(boundary).toHaveCSS(
    "background-color",
    "rgba(255, 255, 255, 0.04)",
  );

  const gender = page
    .locator("summary")
    .filter({ hasText: /^Gender$/ })
    .first();
  await gender.scrollIntoViewIfNeeded();
  await expect(gender).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  await gender.hover();
  await expect(gender).toHaveCSS(
    "background-color",
    "rgba(255, 255, 255, 0.04)",
  );
});

test("custom native controls retain system affordances in forced colors", async ({
  page,
}) => {
  await page.emulateMedia({ forcedColors: "active" });
  await mockNuxtExternalServices(page);
  await page.goto("./");
  await expect(page.locator(".civic-dashboard-browser-explorer")).toHaveAttribute(
    "aria-busy",
    "false",
  );

  const year = page.getByLabel("Viewing data for");
  await expect(year).toHaveCSS("appearance", "auto");
  await expect(year).toHaveCSS("background-image", "none");

  for (const name of [
    "Fatal shootings only",
    "Court search returned a result",
  ]) {
    const control = page.getByRole("checkbox", { name });
    await expect(control).toHaveCSS("appearance", "auto");
    await expect(control).toHaveCSS("background-image", "none");
    const geometry = await control.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        height: parseFloat(style.height),
        width: parseFloat(style.width),
      };
    });
    expect(geometry.width).toBeCloseTo(geometry.height, 1);
  }
});
