import { expect, test, type Locator, type Page } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";

async function openDashboard(page: Page): Promise<Locator> {
  await mockNuxtExternalServices(page);
  await page.goto("./");

  const explorer = page.locator(".civic-dashboard-browser-explorer");
  await expect(explorer).toHaveAttribute("aria-busy", "false");

  const sidebar = page.getByRole("complementary", {
    name: "Map filters and controls",
  });
  await expect(sidebar).toBeVisible();
  return sidebar;
}

async function controlPaint(locator: Locator) {
  return locator.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      backgroundColor: style.backgroundColor,
      borderBottomColor: style.borderBottomColor,
      borderLeftColor: style.borderLeftColor,
      borderRightColor: style.borderRightColor,
      borderTopColor: style.borderTopColor,
      boxShadow: style.boxShadow,
      color: style.color,
      cursor: style.cursor,
      opacity: style.opacity,
      transform: style.transform,
    };
  });
}

async function directTextCenterY(locator: Locator): Promise<number> {
  return locator.evaluate((element) => {
    const textNode = Array.from(element.childNodes).find(
      (node) =>
        node.nodeType === Node.TEXT_NODE && Boolean(node.textContent?.trim()),
    );
    if (!textNode) throw new Error("Expected a direct text node");

    const range = document.createRange();
    range.selectNodeContents(textNode);
    const bounds = range.getBoundingClientRect();
    return bounds.top + bounds.height / 2;
  });
}

async function expectContextualResetAlignment(
  panel: Locator,
  resetName: string,
): Promise<void> {
  const summary = panel.locator("summary");
  const reset = panel.locator("..").getByRole("button", { name: resetName });
  await expect(reset).toBeVisible();

  const [summaryCenter, resetCenter] = await Promise.all([
    directTextCenterY(summary),
    directTextCenterY(reset),
  ]);
  expect(Math.abs(resetCenter - summaryCenter)).toBeLessThanOrEqual(1);
}

test("disabled Reset All Filters keeps its paint on hover and exposes native disabled semantics", async ({
  page,
}) => {
  const sidebar = await openDashboard(page);
  const resetAll = sidebar.getByRole("button", {
    name: "Reset All Filters",
  });

  await expect(resetAll).toBeDisabled();
  await expect(resetAll).toHaveAttribute("disabled", "");
  await expect(resetAll).toHaveCSS("cursor", "default");

  const restingPaint = await controlPaint(resetAll);
  await resetAll.hover();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  await expect.poll(() => controlPaint(resetAll)).toEqual(restingPaint);
});

test("disabled secondary controls do not advertise hover interaction", async ({
  page,
}) => {
  const sidebar = await openDashboard(page);

  const year = page.getByLabel("Viewing data for");
  await year.evaluate((element: HTMLSelectElement) => {
    element.disabled = true;
  });
  await expect(year).toBeDisabled();
  await expect(year).toHaveCSS("cursor", "default");
  const restingYearPaint = await controlPaint(year);
  await year.hover();
  await expect.poll(() => controlPaint(year)).toEqual(restingYearPaint);

  const onlyPoints = sidebar.getByRole("button", {
    name: "Select only Point locations for Map layers",
  });
  await sidebar
    .getByText("Point locations", { exact: true })
    .hover();
  await onlyPoints.evaluate((element: HTMLButtonElement) => {
    element.disabled = true;
  });
  await expect(onlyPoints).toBeDisabled();
  await expect(onlyPoints).toHaveCSS("cursor", "default");
  await expect(onlyPoints).toHaveCSS("opacity", "0");
  await expect(onlyPoints).toHaveCSS("pointer-events", "none");

  let releaseBoundaryRequest = () => {};
  const boundaryRequestGate = new Promise<void>((resolve) => {
    releaseBoundaryRequest = resolve;
  });
  await page.route("**/boundaries/zip_codes", async (route) => {
    await boundaryRequestGate;
    await route.continue();
  });

  const printMap = page.getByRole("button", { name: "Print map" });
  await page
    .getByRole("combobox", { name: "Choropleth Layer" })
    .selectOption("zip-codes");
  await expect(printMap).toBeDisabled();
  await expect(printMap).toHaveCSS("cursor", "wait");
  const restingPrintPaint = await controlPaint(printMap);
  await printMap.hover();
  await expect.poll(() => controlPaint(printMap)).toEqual(restingPrintPaint);
  releaseBoundaryRequest();
});

for (const viewport of [
  { height: 720, label: "desktop", width: 1280 },
  { height: 812, label: "375px", width: 375 },
]) {
  test(`contextual filter reset text is vertically aligned at ${viewport.label}`, async ({
    page,
  }) => {
    await page.setViewportSize({
      height: viewport.height,
      width: viewport.width,
    });
    const sidebar = await openDashboard(page);
    const panels = sidebar.locator("details.civic-disclosure-panel");

    const genderPanel = panels.filter({
      has: page.locator("summary", { hasText: /^Gender$/ }),
    });
    await genderPanel.locator("summary").click();
    await genderPanel
      .getByRole("checkbox", { name: "Male", exact: true })
      .uncheck();
    const genderReset = genderPanel.locator("..").getByRole("button", {
      name: "Reset Gender filter",
    });
    await expect(genderReset).toBeVisible();
    await genderPanel.locator("summary").click();
    await expect(genderPanel).not.toHaveAttribute("open", "");
    await expect(genderReset).toBeVisible();
    await expectContextualResetAlignment(
      genderPanel,
      "Reset Gender filter",
    );

    const agePanel = panels.filter({
      has: page.locator("summary", { hasText: /^Age$/ }),
    });
    await agePanel.locator("summary").click();
    await agePanel
      .getByRole("checkbox", { name: "Exclude unknown values" })
      .check();
    await expectContextualResetAlignment(agePanel, "Reset Age filter");
  });
}
