import { expect, test } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";

const mapCenter = { latitude: 39.9526, longitude: -75.1652 };
const fatalPoint = { latitude: 39.9526, longitude: -75.1602 };
const mapZoom = 11;

function worldPoint(longitude: number, latitude: number) {
  const scale = 512 * 2 ** mapZoom;
  const latitudeRadians = (latitude * Math.PI) / 180;
  return {
    x: ((longitude + 180) / 360) * scale,
    y:
      ((1 - Math.asinh(Math.tan(latitudeRadians)) / Math.PI) / 2) * scale,
  };
}

test("matches the production shooting-victim tooltip", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockNuxtExternalServices(page);
  await page.goto("./");

  const explorer = page.locator(".civic-dashboard-browser-explorer");
  await expect(explorer).toHaveAttribute("aria-busy", "false");

  const canvas = page.locator(".maplibregl-canvas");
  await expect(canvas).toHaveAttribute(
    "aria-label",
    /3 shooting-victim locations/,
  );
  await canvas.scrollIntoViewIfNeeded();

  const canvasBox = await canvas.boundingBox();
  expect(canvasBox).not.toBeNull();
  const center = worldPoint(mapCenter.longitude, mapCenter.latitude);
  const point = worldPoint(fatalPoint.longitude, fatalPoint.latitude);
  const marker = {
    x: (canvasBox?.x ?? 0) + (canvasBox?.width ?? 0) / 2 + point.x - center.x,
    y: (canvasBox?.y ?? 0) + (canvasBox?.height ?? 0) / 2 + point.y - center.y,
  };

  await page.mouse.move(marker.x, marker.y);
  const popup = page.locator(".civic-dashboard-point-popup");
  const tooltip = popup.locator(".civic-map-tooltip");
  await expect(popup).toBeVisible();
  await expect(tooltip).toContainText("Fatal");
  await expect(tooltip).toContainText("Shooting Incident");
  await expect(tooltip).toContainText("Mon, Jan 5, 2026");
  await expect(tooltip).toContainText("1:00 AM");
  await expect(tooltip).toContainText("1200 MARKET ST");
  await expect(tooltip).toContainText("Victim Information");
  await expect(tooltip).toContainText("24 years old");
  await expect(tooltip).toContainText("Black (Non-Hispanic)");
  await expect(tooltip).toContainText("Male");
  await expect(tooltip).toContainText("Case Information");
  await expect(tooltip).toContainText("2026-01");
  await expect(tooltip).toContainText("Court CaseYes");
  await expect(tooltip).not.toContainText("Nearest-street context");

  expect(
    await tooltip
      .locator(".civic-map-tooltip__section-heading")
      .allTextContents(),
  ).toEqual(["Victim Information", "Case Information"]);
  await expect(tooltip.locator(".civic-map-tooltip__row")).toHaveCount(8);

  const visualContract = await popup.evaluate((element) => {
    const content = element.querySelector<HTMLElement>(
      ".maplibregl-popup-content",
    );
    const root = element.querySelector<HTMLElement>(".civic-map-tooltip");
    const badge = element.querySelector<HTMLElement>(
      ".civic-map-tooltip__badge",
    );
    const title = element.querySelector<HTMLElement>(
      ".civic-map-tooltip__title",
    );
    const label = element.querySelector<HTMLElement>(
      ".civic-map-tooltip__label",
    );
    const value = element.querySelector<HTMLElement>(
      ".civic-map-tooltip__value",
    );
    const section = element.querySelector<HTMLElement>(
      ".civic-map-tooltip__section-heading",
    );
    if (!content || !root || !badge || !title || !label || !value || !section) {
      return null;
    }

    return {
      badge: {
        background: getComputedStyle(badge).backgroundColor,
        borderRadius: getComputedStyle(badge).borderRadius,
        fontSize: getComputedStyle(badge).fontSize,
        fontWeight: getComputedStyle(badge).fontWeight,
        padding: getComputedStyle(badge).padding,
      },
      content: {
        background: getComputedStyle(content).backgroundColor,
        border: getComputedStyle(content).border,
        borderRadius: getComputedStyle(content).borderRadius,
        boxShadow: getComputedStyle(content).boxShadow,
        padding: getComputedStyle(content).padding,
      },
      hint: getComputedStyle(root, "::after").content,
      labelWeight: getComputedStyle(label).fontWeight,
      root: {
        fontSize: getComputedStyle(root).fontSize,
        lineHeight: getComputedStyle(root).lineHeight,
        maxWidth: getComputedStyle(root).maxWidth,
        minWidth: getComputedStyle(root).minWidth,
      },
      sectionWeight: getComputedStyle(section).fontWeight,
      titleWeight: getComputedStyle(title).fontWeight,
      valueWeight: getComputedStyle(value).fontWeight,
    };
  });
  expect(visualContract).toEqual({
    badge: {
      background: "rgba(216, 69, 69, 0.9)",
      borderRadius: "4px",
      fontSize: "10px",
      fontWeight: "600",
      padding: "3px 8px",
    },
    content: {
      background: "rgba(30, 30, 30, 0.95)",
      border: "1px solid rgba(255, 255, 255, 0.1)",
      borderRadius: "8px",
      boxShadow: "rgba(0, 0, 0, 0.4) 0px 4px 20px 0px",
      padding: "12px 14px",
    },
    hint: '"Click to pin"',
    labelWeight: "400",
    root: {
      fontSize: "13px",
      lineHeight: "18.2px",
      maxWidth: "280px",
      minWidth: "180px",
    },
    sectionWeight: "600",
    titleWeight: "600",
    valueWeight: "500",
  });

  await page.mouse.click(marker.x, marker.y);
  await expect(popup).toHaveClass(/civic-dashboard-point-popup--pinned/);
  await expect(popup.locator(".maplibregl-popup-close-button")).toBeVisible();
  expect(
    await tooltip.evaluate(
      (element) => getComputedStyle(element, "::after").content,
    ),
  ).toBe("none");
});
