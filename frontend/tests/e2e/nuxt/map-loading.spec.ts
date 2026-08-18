import { expect, test, type Page } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";

const apiHeaders = { "access-control-allow-origin": "*" };

async function openReadyMap(page: Page) {
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
  await expect(page.locator(".civic-dashboard-map-loading")).toHaveCount(0);
}

for (const viewport of [
  { height: 900, label: "desktop", width: 1280 },
  { height: 812, label: "mobile", width: 375 },
]) {
  test(`keeps map progress below Home at ${viewport.label} width and honors reduced motion`, async ({
    page,
  }) => {
    await page.setViewportSize({ height: viewport.height, width: viewport.width });
    await openReadyMap(page);

    let markRequestStarted!: () => void;
    let releaseResponse!: () => void;
    const requestStarted = new Promise<void>((resolve) => {
      markRequestStarted = resolve;
    });
    const responseReleased = new Promise<void>((resolve) => {
      releaseResponse = resolve;
    });
    await page.route("**/boundaries/police_districts", async (route) => {
      markRequestStarted();
      await responseReleased;
      await route.fulfill({
        body: JSON.stringify({ type: "FeatureCollection", features: [] }),
        contentType: "application/json",
        headers: apiHeaders,
      });
    });

    await page
      .getByRole("combobox", { name: "Choropleth Layer" })
      .selectOption("police-districts");
    await requestStarted;

    const frame = page.locator(".civic-dashboard-point-map__frame");
    const printMap = page.getByRole("button", { name: "Print map" });
    const progress = page.getByRole("progressbar", {
      name: "Loading map data",
    });
    await expect(progress).toBeVisible();
    await expect(printMap).toBeDisabled();
    await expect(progress).not.toHaveAttribute("aria-valuenow", /.+/);
    await expect(progress).not.toHaveAttribute("aria-live", /.+/);
    await expect(frame).toHaveAttribute("aria-busy", "true");

    const geometry = await frame.evaluate((element) => {
      const home = element.querySelector<HTMLElement>(".maplibregl-ctrl-home");
      const spinner = element.querySelector<HTMLElement>(
        ".civic-dashboard-map-loading",
      );
      if (!home || !spinner) return null;

      const frameRect = element.getBoundingClientRect();
      const homeRect = home.getBoundingClientRect();
      const spinnerRect = spinner.getBoundingClientRect();
      return {
        height: spinnerRect.height,
        homeRightInset: frameRect.right - homeRect.right,
        rightInset: frameRect.right - spinnerRect.right,
        topInset: spinnerRect.top - frameRect.top,
        verticalGap: spinnerRect.top - homeRect.bottom,
        width: spinnerRect.width,
      };
    });
    expect(geometry).not.toBeNull();
    expect(geometry?.width).toBeCloseTo(32, 0);
    expect(geometry?.height).toBeCloseTo(32, 0);
    expect(geometry?.topInset).toBeCloseTo(150, 0);
    expect(geometry?.verticalGap).toBeCloseTo(43, 0);
    expect(geometry?.rightInset).toBeCloseTo(10, 0);
    expect(geometry?.rightInset).toBeCloseTo(
      geometry?.homeRightInset ?? Number.POSITIVE_INFINITY,
      0,
    );

    const normalMotion = await progress.evaluate((element) => {
      const svg = element.querySelector("svg")!;
      const indicator = element.querySelector(
        ".civic-dashboard-map-loading__indicator",
      )!;
      return {
        indicator: {
          duration: getComputedStyle(indicator).animationDuration,
          iterations: getComputedStyle(indicator).animationIterationCount,
          name: getComputedStyle(indicator).animationName,
        },
        spinner: {
          duration: getComputedStyle(svg).animationDuration,
          iterations: getComputedStyle(svg).animationIterationCount,
          name: getComputedStyle(svg).animationName,
        },
      };
    });
    expect(normalMotion.spinner.name).not.toBe("none");
    expect(normalMotion.spinner.duration).toBe("1.4s");
    expect(normalMotion.spinner.iterations).toBe("infinite");
    expect(normalMotion.indicator.name).not.toBe("none");
    expect(normalMotion.indicator.duration).toBe("1.4s");
    expect(normalMotion.indicator.iterations).toBe("infinite");

    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect(progress).toBeVisible();
    const reducedMotion = await progress.evaluate((element) => {
      const animated = [
        element.querySelector("svg")!,
        element.querySelector(".civic-dashboard-map-loading__indicator")!,
      ];
      return animated.map((target) => {
        const style = getComputedStyle(target);
        return {
          durationSeconds: Number.parseFloat(style.animationDuration),
          iterations: style.animationIterationCount,
        };
      });
    });
    expect(reducedMotion).toEqual([
      { durationSeconds: 0.00001, iterations: "1" },
      { durationSeconds: 0.00001, iterations: "1" },
    ]);

    releaseResponse();
    await expect(progress).toHaveCount(0);
    await expect(frame).toHaveAttribute("aria-busy", "false");
    await expect(printMap).toBeEnabled();
  });
}
