import { expect, test, type Page } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";

const apiHeaders = { "access-control-allow-origin": "*" };

async function waitForMap(page: Page) {
  const explorer = page.locator(".civic-dashboard-browser-explorer");
  await expect(explorer).toHaveAttribute("aria-busy", "false");
  const canvas = page.locator(".maplibregl-canvas");
  await canvas.scrollIntoViewIfNeeded();
  const box = await canvas.boundingBox();
  expect(box).not.toBeNull();
  return {
    canvas,
    center: {
      x: (box?.x ?? 0) + (box?.width ?? 0) / 2,
      y: (box?.y ?? 0) + (box?.height ?? 0) / 2,
    },
  };
}

async function expectProductionAggregatePopup(page: Page, title: string) {
  const popup = page.locator(".map-tooltip-popup");
  const tooltip = popup.locator(".map-tooltip");
  await expect(popup).toBeVisible();
  await expect(tooltip.locator(".tooltip-title")).toHaveText(title);
  await expect(tooltip.locator(".tooltip-stat-value")).toHaveText("1");
  await expect(tooltip.locator(".tooltip-stat-label")).toHaveText(
    "shooting victims",
  );
  await expect(tooltip).not.toContainText("Fatal");
  await expect(tooltip).not.toContainText("Nonfatal");

  expect(
    await popup.evaluate((element) => {
      const content = element.querySelector<HTMLElement>(
        ".maplibregl-popup-content",
      );
      const root = element.querySelector<HTMLElement>(".map-tooltip");
      const titleElement = element.querySelector<HTMLElement>(".tooltip-title");
      const stat = element.querySelector<HTMLElement>(".tooltip-stat");
      const value = element.querySelector<HTMLElement>(".tooltip-stat-value");
      const label = element.querySelector<HTMLElement>(".tooltip-stat-label");
      if (!content || !root || !titleElement || !stat || !value || !label) {
        return null;
      }
      const rect = element.getBoundingClientRect();
      return {
        content: {
          background: getComputedStyle(content).backgroundColor,
          border: getComputedStyle(content).border,
          borderRadius: getComputedStyle(content).borderRadius,
          boxShadow: getComputedStyle(content).boxShadow,
          padding: getComputedStyle(content).padding,
          pointerEvents: getComputedStyle(content).pointerEvents,
        },
        hint: getComputedStyle(root, "::after").content,
        popup: {
          height: Math.round(rect.height),
          width: Math.round(rect.width),
        },
        root: {
          fontSize: getComputedStyle(root).fontSize,
          lineHeight: getComputedStyle(root).lineHeight,
          maxWidth: getComputedStyle(root).maxWidth,
          minWidth: getComputedStyle(root).minWidth,
        },
        stat: { padding: getComputedStyle(stat).padding },
        statLabel: {
          fontSize: getComputedStyle(label).fontSize,
          fontWeight: getComputedStyle(label).fontWeight,
          letterSpacing: getComputedStyle(label).letterSpacing,
          textTransform: getComputedStyle(label).textTransform,
        },
        statValue: {
          fontSize: getComputedStyle(value).fontSize,
          fontWeight: getComputedStyle(value).fontWeight,
          lineHeight: getComputedStyle(value).lineHeight,
        },
        title: {
          fontSize: getComputedStyle(titleElement).fontSize,
          fontWeight: getComputedStyle(titleElement).fontWeight,
          marginBottom: getComputedStyle(titleElement).marginBottom,
          paddingBottom: getComputedStyle(titleElement).paddingBottom,
        },
      };
    }),
  ).toEqual({
    content: {
      background: "rgba(30, 30, 30, 0.95)",
      border: "1px solid rgba(255, 255, 255, 0.1)",
      borderRadius: "8px",
      boxShadow: "rgba(0, 0, 0, 0.4) 0px 4px 20px 0px",
      padding: "12px 14px",
      pointerEvents: "none",
    },
    hint: '"Click to pin"',
    popup: { height: 163, width: 210 },
    root: {
      fontSize: "13px",
      lineHeight: "18.2px",
      maxWidth: "280px",
      minWidth: "180px",
    },
    stat: { padding: "8px 0px" },
    statLabel: {
      fontSize: "11px",
      fontWeight: "400",
      letterSpacing: "0.5px",
      textTransform: "uppercase",
    },
    statValue: {
      fontSize: "28px",
      fontWeight: "700",
      lineHeight: "28px",
    },
    title: {
      fontSize: "14px",
      fontWeight: "600",
      marginBottom: "8px",
      paddingBottom: "6px",
    },
  });

  return { popup, tooltip };
}

test("matches the production choropleth hover and pinned tooltip", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockNuxtExternalServices(page);
  await page.route("**/boundaries/police_districts", (route) =>
    route.fulfill({
      body: JSON.stringify({
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: {
              type: "Polygon",
              coordinates: [
                [
                  [-75.3, 39.8],
                  [-75.0, 39.8],
                  [-75.0, 40.1],
                  [-75.3, 40.1],
                  [-75.3, 39.8],
                ],
              ],
            },
            properties: { police_district: "6" },
          },
        ],
      }),
      contentType: "application/json",
      headers: apiHeaders,
    }),
  );
  await page.goto("./?layers=police-districts");
  await expect(
    page.getByRole("img", {
      name: /Shooting victims by police district map legend/i,
    }),
  ).toBeVisible();

  const { canvas, center } = await waitForMap(page);
  await page.mouse.move(center.x, center.y);
  const { popup, tooltip } = await expectProductionAggregatePopup(
    page,
    "Police District #6",
  );
  await expect(canvas).toHaveCSS("cursor", "grab");
  await expect(page.locator(".civic-dashboard-map-selection")).toHaveCount(0);

  await page.mouse.click(center.x, center.y);
  await expect(popup).toHaveClass(/map-tooltip-popup--pinned/);
  await expect(popup.locator(".maplibregl-popup-close-button")).toBeVisible();
  expect(
    await tooltip.evaluate(
      (element) => getComputedStyle(element, "::after").content,
    ),
  ).toBe("none");
  await expect(popup.locator(".maplibregl-popup-content")).toHaveCSS(
    "border",
    "1px solid rgba(100, 149, 237, 0.5)",
  );
});

test("uses the production street-block title and tooltip behavior", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockNuxtExternalServices(page);
  await page.route("**/streets?**", (route) =>
    route.fulfill({
      body: JSON.stringify({
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: {
              type: "LineString",
              coordinates: [
                [-75.3, 39.9526],
                [-75.0, 39.9526],
              ],
            },
            properties: {
              block_label: "1200 BLOCK MARKET ST",
              block_number: 1200,
              segment_id: "segment-1",
              street_name: "MARKET ST",
            },
          },
        ],
      }),
      contentType: "application/json",
      headers: apiHeaders,
    }),
  );
  await page.goto("./?layers=hot-spots-by-street-block");
  await expect(page.getByRole("img", { name: /street block/ })).toBeVisible();

  const { center } = await waitForMap(page);
  await page.mouse.move(center.x, center.y);
  const { popup } = await expectProductionAggregatePopup(
    page,
    "1200 MARKET ST",
  );

  await page.mouse.click(center.x, center.y);
  await expect(popup).toHaveClass(/map-tooltip-popup--pinned/);
  await expect(popup.locator(".maplibregl-popup-close-button")).toBeVisible();
});
