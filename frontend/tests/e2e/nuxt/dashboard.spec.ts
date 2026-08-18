import { expect, test, type Locator, type Page } from "@playwright/test";

import {
  mockNuxtExternalServices,
  shootingRows,
} from "../support/mockApi";

const apiOrigin = "http://127.0.0.1:4181";
const appOrigin = "http://127.0.0.1:4180";
const dataAttribution =
  "Shooting-victim records: Philadelphia Police Department via OpenDataPhilly.";
const basemapAttribution =
  "Sources: Esri, HERE, Garmin, FAO, NOAA, USGS, © OpenStreetMap contributors, and the GIS User Community.";

function pdfPrintContract(pdf: Buffer) {
  const source = pdf.toString("latin1");
  return {
    mediaBoxes: [
      ...source.matchAll(
        /\/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]/g,
      ),
    ].map(([, width, height]) => ({
      height: Number(height),
      width: Number(width),
    })),
    pageCount: source.match(/\/Type\s*\/Page\b/g)?.length ?? 0,
  };
}

async function openDashboard(
  page: Page,
  { startFromStats = false }: { startFromStats?: boolean } = {},
) {
  const apiResponses: Array<{ cors: string | undefined; path: string }> = [];
  page.on("response", async (response) => {
    const url = new URL(response.url());
    if (url.origin !== apiOrigin) return;
    apiResponses.push({
      cors: (await response.allHeaders())["access-control-allow-origin"],
      path: url.pathname,
    });
  });

  await mockNuxtExternalServices(page);
  if (startFromStats) {
    await page.goto("./stats");
    await page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link", { exact: true, name: "Explore" })
      .click();
    await expect(page).toHaveURL(/\/philly-gun-violence-map\/$/);
  } else {
    await page.goto("./");
  }
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Mapping Philadelphia's Gun Violence",
    }),
  ).toBeVisible();

  const explorer = page.locator(".civic-dashboard-browser-explorer");
  await expect(explorer).toHaveAttribute("aria-busy", "false");
  await expect(page.locator(".civic-dashboard-point-map")).toHaveClass(
    /civic-dashboard-point-map--ready/,
  );
  const sidebar = page.getByRole("complementary", {
    name: "Map filters and controls",
  });
  await expect(sidebar).toBeVisible();
  await expect(page.locator(".maplibregl-canvas")).toHaveAttribute(
    "aria-label",
    /3 shooting-victim locations/,
  );

  return { apiResponses, sidebar };
}

async function expectActiveLegendPrint(
  page: Page,
  id: "choropleth" | "street-hot-spots",
  liveLegend: Locator,
) {
  const liveAccessibleName = await liveLegend.getAttribute("aria-label");
  const liveBarStyle = await liveLegend
    .locator("[data-map-legend-bar]")
    .getAttribute("style");
  const liveTicks = await liveLegend
    .locator("[data-map-legend-tick]")
    .allTextContents();
  const liveZeroCount = await liveLegend.locator("[data-map-legend-zero]").count();
  expect(liveAccessibleName).not.toBeNull();
  expect(liveBarStyle).not.toBeNull();

  await page.getByRole("button", { name: "Print map" }).click();
  await expect(page.locator("html")).toHaveAttribute(
    "data-map-print-invoked",
    "true",
  );
  const sheet = page.locator(".civic-dashboard-map-print-sheet");
  const printLegend = sheet.locator(`[data-map-legend="${id}"]`);
  await expect(printLegend).toHaveAttribute(
    "aria-label",
    liveAccessibleName!,
  );
  await expect(printLegend.locator("[data-map-legend-bar]")).toHaveAttribute(
    "style",
    liveBarStyle!,
  );
  await expect(printLegend.locator("[data-map-legend-tick]")).toHaveText(
    liveTicks,
  );
  await expect(printLegend.locator("[data-map-legend-zero]")).toHaveCount(
    liveZeroCount,
  );

  await page.setViewportSize({ height: 960, width: 720 });
  await page.emulateMedia({ media: "print" });
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  await expect(printLegend).toBeVisible();
  const containment = await printLegend.evaluate((element) => {
    const legend = element.getBoundingClientRect();
    const sheet = element
      .closest(".civic-dashboard-map-print-sheet")
      ?.getBoundingClientRect();
    return sheet
      ? {
          bottom: legend.bottom <= sheet.bottom + 1,
          left: legend.left >= sheet.left - 1,
          right: legend.right <= sheet.right + 1,
          top: legend.top >= sheet.top - 1,
        }
      : null;
  });
  expect(containment).toEqual({
    bottom: true,
    left: true,
    right: true,
    top: true,
  });

  const pdf = await page.pdf({
    displayHeaderFooter: true,
    preferCSSPageSize: true,
    printBackground: true,
    tagged: false,
  });
  expect(pdfPrintContract(pdf).pageCount).toBe(1);
  await expect(sheet).not.toBeAttached();
}

test("prepares one attributed print map without opening the system dialog", async ({
  page,
}) => {
  await page.addInitScript(() => {
    window.print = () => {
      document.documentElement.dataset.mapPrintInvoked = "true";
    };
  });
  await openDashboard(page, { startFromStats: true });

  const printButton = page.getByRole("button", { name: "Print map" });
  await printButton.click();
  await expect(page.locator("html")).toHaveAttribute(
    "data-map-print-invoked",
    "true",
  );

  const sheet = page.locator(".civic-dashboard-map-print-sheet");
  await expect(sheet).toBeAttached();
  const title = sheet.locator("h1");
  const legend = sheet.locator(".civic-dashboard-map-print-sheet__legend");
  const attribution = sheet.locator("footer p");
  await expect(title).toHaveText(
    "Philadelphia shooting-victim map — 2026",
  );
  await expect(legend).toContainText("Fatal — 1");
  await expect(legend).toContainText("Nonfatal — 2");
  await expect(legend.locator("[data-map-legend]")).toHaveCount(0);
  await expect(attribution).toHaveText([dataAttribution, basemapAttribution]);
  expect(await sheet.locator("img").getAttribute("src")).toMatch(
    /^data:image\/png;base64,/,
  );
  await expect(page.locator(".maplibregl-map")).toHaveCount(1);
  await page.setViewportSize({ height: 960, width: 720 });
  await page.emulateMedia({ media: "print" });
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  await expect(sheet).toBeVisible();
  await expect(title).toBeVisible();
  await expect(legend).toBeVisible();
  await expect(attribution.nth(0)).toBeVisible();
  await expect(attribution.nth(1)).toBeVisible();
  const printContract = await sheet.evaluate((element) => {
    const image = element.querySelector<HTMLImageElement>("img");
    if (!image) return null;

    const sheetStyle = getComputedStyle(element);
    const sheetRect = element.getBoundingClientRect();
    const imageRect = image.getBoundingClientRect();
    const containedElements = [
      element.querySelector<HTMLElement>("header"),
      image,
      element.querySelector<HTMLElement>(
        ".civic-dashboard-map-print-sheet__legend",
      ),
      element.querySelector<HTMLElement>("footer"),
    ].filter((candidate): candidate is HTMLElement => candidate !== null);
    const renderedOutsideSheet = Array.from(
      document.body.querySelectorAll<HTMLElement>("*"),
    )
      .filter((candidate) => candidate !== element && !element.contains(candidate))
      .filter((candidate) => {
        const style = getComputedStyle(candidate);
        const rect = candidate.getBoundingClientRect();
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          rect.width > 0 &&
          rect.height > 0
        );
      })
      .map((candidate) => candidate.className || candidate.tagName);

    return {
      containedElements: containedElements.map((candidate) => {
        const bounds = candidate.getBoundingClientRect();
        return {
          bottom: bounds.bottom,
          left: bounds.left,
          right: bounds.right,
          top: bounds.top,
        };
      }),
      imageBottom: imageRect.bottom,
      imageContentRatio: image.naturalWidth / image.naturalHeight,
      imageHeight: imageRect.height,
      imageLeft: imageRect.left,
      imageNaturalHeight: image.naturalHeight,
      imageNaturalWidth: image.naturalWidth,
      imageRenderedRatio: imageRect.width / imageRect.height,
      imageWidth: imageRect.width,
      renderedOutsideSheet,
      rootClientWidth: document.documentElement.clientWidth,
      rootScrollWidth: document.documentElement.scrollWidth,
      sheetBottom: sheetRect.bottom,
      sheetClientHeight: element.clientHeight,
      sheetClientWidth: element.clientWidth,
      sheetContentLeft:
        sheetRect.left +
        Number.parseFloat(sheetStyle.borderLeftWidth) +
        Number.parseFloat(sheetStyle.paddingLeft),
      sheetContentWidth:
        sheetRect.width -
        Number.parseFloat(sheetStyle.borderLeftWidth) -
        Number.parseFloat(sheetStyle.borderRightWidth) -
        Number.parseFloat(sheetStyle.paddingLeft) -
        Number.parseFloat(sheetStyle.paddingRight),
      sheetHeight: sheetRect.height,
      sheetLeft: sheetRect.left,
      sheetRight: sheetRect.right,
      sheetScrollHeight: element.scrollHeight,
      sheetScrollWidth: element.scrollWidth,
      sheetTop: sheetRect.top,
      sheetWidth: sheetRect.width,
    };
  });
  expect(printContract).not.toBeNull();
  expect(printContract?.renderedOutsideSheet).toEqual([]);
  expect(printContract?.rootClientWidth).toBe(720);
  expect(printContract?.rootScrollWidth).toBeLessThanOrEqual(721);
  expect(printContract?.sheetLeft).toBeCloseTo(0, 0);
  expect(printContract?.sheetTop).toBeCloseTo(0, 0);
  expect(printContract?.sheetWidth).toBeLessThanOrEqual(720);
  expect(printContract?.sheetHeight).toBeLessThanOrEqual(960);
  expect(printContract?.sheetBottom).toBeLessThanOrEqual(960);
  expect(printContract?.sheetScrollWidth).toBeLessThanOrEqual(
    (printContract?.sheetClientWidth ?? 0) + 1,
  );
  expect(printContract?.sheetScrollHeight).toBeLessThanOrEqual(
    (printContract?.sheetClientHeight ?? 0) + 1,
  );
  expect(printContract?.containedElements).toHaveLength(4);
  for (const bounds of printContract?.containedElements ?? []) {
    expect(bounds.left).toBeGreaterThanOrEqual(printContract?.sheetLeft ?? 0);
    expect(bounds.right).toBeLessThanOrEqual(
      (printContract?.sheetRight ?? 0) + 1,
    );
    expect(bounds.top).toBeGreaterThanOrEqual(printContract?.sheetTop ?? 0);
    expect(bounds.bottom).toBeLessThanOrEqual(
      (printContract?.sheetBottom ?? 0) + 1,
    );
  }
  expect(printContract?.imageLeft).toBeCloseTo(
    printContract?.sheetContentLeft ?? Number.POSITIVE_INFINITY,
    1,
  );
  expect(printContract?.imageWidth).toBeCloseTo(
    printContract?.sheetContentWidth ?? Number.POSITIVE_INFINITY,
    1,
  );
  expect(printContract?.imageNaturalWidth).toBeGreaterThan(0);
  expect(printContract?.imageNaturalHeight).toBeGreaterThan(0);
  expect(printContract?.imageHeight).toBeGreaterThan(0);
  expect(printContract?.imageBottom).toBeLessThanOrEqual(
    printContract?.sheetBottom ?? 0,
  );
  expect(printContract?.imageRenderedRatio).toBeCloseTo(
    printContract?.imageContentRatio ?? Number.POSITIVE_INFINITY,
    2,
  );

  const letterPdf = await page.pdf({
    displayHeaderFooter: true,
    preferCSSPageSize: true,
    printBackground: true,
    tagged: false,
  });
  const letterContract = pdfPrintContract(letterPdf);
  expect(letterContract.pageCount).toBe(1);
  expect(letterContract.mediaBoxes).toEqual([{ height: 792, width: 612 }]);
  await expect(sheet).not.toBeAttached();

  await page.emulateMedia({ media: "screen" });
  await printButton.click();
  await expect(sheet).toBeAttached();
  await page.emulateMedia({ media: "print" });
  await expect(sheet).toBeVisible();
  await expect(sheet.locator("img")).toBeVisible();

  const a4Pdf = await page.pdf({
    displayHeaderFooter: true,
    format: "A4",
    preferCSSPageSize: false,
    printBackground: true,
    tagged: false,
  });
  const a4Contract = pdfPrintContract(a4Pdf);
  expect(a4Contract.pageCount).toBe(1);
  expect(a4Contract.mediaBoxes).toHaveLength(1);
  expect(a4Contract.mediaBoxes[0].width).toBeCloseTo(595.92, 1);
  expect(a4Contract.mediaBoxes[0].height).toBeCloseTo(842.88, 1);
  expect(a4Contract.mediaBoxes[0].width).toBeLessThan(
    a4Contract.mediaBoxes[0].height,
  );
  await expect(sheet).not.toBeAttached();
});

test("prints active choropleth and street hot-spot legends on one page", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.addInitScript(() => {
    window.print = () => {
      document.documentElement.dataset.mapPrintInvoked = "true";
    };
  });
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
                  [-75.15, 39.8],
                  [-75.15, 40.1],
                  [-75.3, 40.1],
                  [-75.3, 39.8],
                ],
              ],
            },
            properties: { police_district: "6" },
          },
          {
            type: "Feature",
            geometry: {
              type: "Polygon",
              coordinates: [
                [
                  [-75.15, 39.8],
                  [-75.0, 39.8],
                  [-75.0, 40.1],
                  [-75.15, 40.1],
                  [-75.15, 39.8],
                ],
              ],
            },
            properties: { police_district: "99" },
          },
        ],
      }),
      contentType: "application/json",
      headers: { "access-control-allow-origin": appOrigin },
    }),
  );
  await page.goto("./?layers=police-districts");
  await expect(
    page.locator(".civic-dashboard-browser-explorer"),
  ).toHaveAttribute("aria-busy", "false", { timeout: 30_000 });
  const mapStatus = page.locator("#dashboard-point-map-description");
  await expect(mapStatus).toContainText(
    "Showing 1 of 4 shooting-victim records aggregated by Police Districts in 2026.",
  );
  await expect(mapStatus).toContainText(
    "3 records are not shown in this layer because a matching police district is unavailable.",
  );

  const liveLegend = page.locator(
    '.civic-dashboard-point-map [data-map-legend="choropleth"]',
  );
  await expect(liveLegend).toBeVisible();
  await expect(liveLegend).toHaveAttribute(
    "aria-label",
    "Shooting victims by police district map legend. 1 shooting victim. Gray means no matching victims. Counts reflect the current filters.",
  );
  await expect(liveLegend).toHaveAttribute("data-map-legend-scale", "linear");
  await expect(liveLegend.locator("[data-map-legend-zero]")).toBeVisible();
  await expect(liveLegend.locator("[data-map-legend-max]")).toHaveCount(0);
  await expect(liveLegend.locator("[data-map-legend-tick]")).toHaveText(["1"]);
  await expect(liveLegend).toContainText("Gray: no matching victims.");
  await expect(liveLegend).toContainText("Counts reflect the current filters.");
  const liveBarStyle = await liveLegend
    .locator("[data-map-legend-bar]")
    .getAttribute("style");
  expect(liveBarStyle).toContain("background: rgb(249, 105, 76)");
  await expectActiveLegendPrint(page, "choropleth", liveLegend);

  await page.emulateMedia({ media: "screen" });

  const hotspotRows = shootingRows.map((row, index) => ({
    ...row,
    segment_id: index < 3 ? "segment-1" : "segment-4",
  }));
  await page.route(
    "**/shootings/rows/nuxt-e2e-v1/2026.ndjson",
    (route) =>
      route.fulfill({
        body: hotspotRows.map((row) => JSON.stringify(row)).join("\n"),
        contentType: "application/x-ndjson",
        headers: { "access-control-allow-origin": appOrigin },
      }),
  );
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
                [-75.17, 39.95],
                [-75.15, 39.95],
              ],
            },
            properties: {
              block_label: "1200 BLOCK MARKET ST",
              block_number: 1200,
              segment_id: "segment-1",
              street_name: "MARKET ST",
            },
          },
          {
            type: "Feature",
            geometry: {
              type: "LineString",
              coordinates: [
                [-75.17, 40.01],
                [-75.15, 40.01],
              ],
            },
            properties: {
              block_label: "4300 BLOCK GERMANTOWN AVE",
              block_number: 4300,
              segment_id: "segment-4",
              street_name: "GERMANTOWN AVE",
            },
          },
        ],
      }),
      contentType: "application/json",
      headers: { "access-control-allow-origin": appOrigin },
    }),
  );

  await page.goto("./?layers=point-locations,hot-spots-by-street-block");
  await expect(
    page.locator(".civic-dashboard-browser-explorer"),
  ).toHaveAttribute("aria-busy", "false", { timeout: 30_000 });
  await expect(mapStatus).toContainText(
    "Showing point locations for 3 of 4 shooting-victim records in 2026.",
  );
  await expect(mapStatus).toContainText(
    "Street-block hot spots represent 4 of 4 shooting-victim records in 2026.",
  );

  const hotspotLegend = page.locator(
    '.civic-dashboard-point-map [data-map-legend="street-hot-spots"]',
  );
  await expect(hotspotLegend).toBeVisible();
  await expect(hotspotLegend).toHaveAttribute(
    "aria-label",
    "Shooting victims per street block map legend. Brighter yellow means more victims. Logarithmic scale from 1 to 3. Counts reflect the current filters.",
  );
  await expect(hotspotLegend).toHaveAttribute("data-map-legend-scale", "log");
  await expect(hotspotLegend.locator("[data-map-legend-zero]")).toHaveCount(0);
  await expect(hotspotLegend.locator("[data-map-legend-tick]")).toHaveText([
    "1",
    "2",
    "3",
  ]);
  const midpoint = hotspotLegend.locator(
    '[data-map-legend-tick][data-value="2"]',
  );
  await expect
    .poll(() =>
      midpoint.evaluate((element) => Number.parseFloat(element.style.left)),
    )
    .toBeCloseTo((Math.log(2) / Math.log(3)) * 100, 3);
  await expect(hotspotLegend).toContainText(
    "Brighter yellow means more victims.",
  );
  await expect(hotspotLegend).toContainText(
    "Counts reflect the current filters.",
  );
  const hotspotBarStyle = await hotspotLegend
    .locator("[data-map-legend-bar]")
    .getAttribute("style");
  expect(hotspotBarStyle).toContain("rgb(204, 71, 120) 0%");
  expect(hotspotBarStyle).toContain("rgb(240, 249, 33) 100%");

  await expectActiveLegendPrint(page, "street-hot-spots", hotspotLegend);
});

test("shows chart definitions without changing desktop chart geometry", async ({
  page,
}) => {
  await openDashboard(page);

  const card = page.locator(".civic-dashboard-category-chart--outcome");
  const nextCard = page.locator(".civic-dashboard-category-chart--court");
  const trigger = card.getByRole("button", { name: "About Outcome" });
  const tooltip = card.getByRole("tooltip");
  await page.evaluate(() => document.fonts.ready);

  const measure = async () => {
    const [cardBox, nextBox] = await Promise.all([
      card.boundingBox(),
      nextCard.boundingBox(),
    ]);
    return {
      cardHeight: cardBox?.height,
      cardLeft: cardBox?.x,
      cardRight: cardBox ? cardBox.x + cardBox.width : undefined,
      nextTopRelative:
        cardBox && nextBox ? nextBox.y - cardBox.y : undefined,
    };
  };
  const before = await measure();

  await trigger.hover();
  await expect(tooltip).toBeVisible();
  const whileOpen = await measure();
  const triggerBox = await trigger.boundingBox();
  const tooltipBox = await tooltip.boundingBox();
  expect(whileOpen.cardHeight).toBeCloseTo(before.cardHeight ?? -1, 1);
  expect(whileOpen.nextTopRelative).toBeCloseTo(
    before.nextTopRelative ?? -1,
    1,
  );
  expect(tooltipBox?.x).toBeGreaterThanOrEqual((before.cardLeft ?? 0) - 1);
  expect((tooltipBox?.x ?? 0) + (tooltipBox?.width ?? 0)).toBeLessThanOrEqual(
    (before.cardRight ?? 0) + 1,
  );

  await page.mouse.move(
    (triggerBox?.x ?? 0) + (triggerBox?.width ?? 0) / 2,
    (tooltipBox?.y ?? 0) + 8,
    { steps: 12 },
  );
  await expect(tooltip).toBeVisible();

  await page.mouse.move(0, 0);
  await expect(tooltip).not.toBeVisible();

  await trigger.focus();
  await page.mouse.move(0, 0);
  await expect(tooltip).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(tooltip).not.toBeVisible();

  await trigger.click();
  await expect(tooltip).toBeVisible();
  await page.getByRole("heading", {
    level: 1,
    name: "Mapping Philadelphia's Gun Violence",
  }).click();
  await expect(tooltip).not.toBeVisible();
});

test("hydrates the Nuxt explorer and shares filters with its map, histogram, charts, and download", async ({
  page,
}) => {
  const { apiResponses, sidebar } = await openDashboard(page);

  await expect(
    sidebar.getByText(/Showing locations for\s*3 shooting victims/),
  ).toBeVisible();
  await expect(
    sidebar.getByText("Note: 1 victim not shown due to missing locations"),
  ).toBeVisible();

  const filterPanels = sidebar.locator("details.civic-disclosure-panel");
  await expect(filterPanels).toHaveCount(6);
  expect(
    await filterPanels.evaluateAll((panels) =>
      panels.every((panel) => !(panel as HTMLDetailsElement).open),
    ),
  ).toBe(true);

  const locationNote = sidebar.locator(".civic-legacy-sidebar__note");
  const sidebarHeader = sidebar.locator(".civic-legacy-sidebar__header");
  await page.evaluate(() => document.fonts.ready);
  const initialNoteBox = await locationNote.boundingBox();
  const initialHeaderHeight = await sidebarHeader.evaluate(
    (element) => element.getBoundingClientRect().height,
  );
  await filterPanels.nth(0).locator("summary").click();
  await filterPanels
    .nth(0)
    .getByRole("button", { name: "Select only Female for Gender" })
    .click();
  await expect(locationNote).toHaveAttribute("aria-hidden", "true");
  const emptyNoteBox = await locationNote.boundingBox();
  const filteredHeaderHeight = await sidebarHeader.evaluate(
    (element) => element.getBoundingClientRect().height,
  );
  expect(emptyNoteBox?.height).toBeCloseTo(initialNoteBox?.height ?? -1, 1);
  expect(filteredHeaderHeight).toBeCloseTo(initialHeaderHeight, 1);
  const genderReset = filterPanels
    .nth(0)
    .locator("..")
    .getByRole("button", { name: "Reset Gender filter" });
  await genderReset.click();
  await expect(genderReset).toHaveCount(0);
  await expect(
    sidebar.getByText(/Showing locations for\s*3 shooting victims/),
  ).toBeVisible();
  await filterPanels.nth(0).locator("summary").click();

  const agePanel = filterPanels.filter({
    has: page.locator("summary", { hasText: "Age" }),
  });
  await agePanel.locator("summary").click();
  await expect(
    agePanel.getByRole("img", {
      name: "Age distribution across 30 bins. Bars inside the selected range are highlighted.",
    }),
  ).toBeVisible();
  expect(
    await agePanel
      .locator(".civic-dashboard-range-filter__histogram")
      .evaluate((element) => getComputedStyle(element).backgroundColor),
  ).toBe("rgba(0, 0, 0, 0)");

  const ageEnd = agePanel.getByRole("slider", { name: "Age end" });
  await ageEnd.evaluate((element) => {
    const input = element as HTMLInputElement;
    input.value = "30";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect(
    sidebar.getByText(/Showing locations for\s*2 shooting victims/),
  ).toBeVisible();
  await expect(
    agePanel.locator(".civic-dashboard-range-filter__bar--selected"),
  ).toHaveCount(9);

  await agePanel
    .locator("..")
    .getByRole("button", { name: "Reset Age filter" })
    .click();
  await expect(
    sidebar.getByText(/Showing locations for\s*3 shooting victims/),
  ).toBeVisible();

  const fatalOnly = sidebar.getByRole("checkbox", {
    name: "Fatal shootings only",
  });
  await fatalOnly.check();
  await expect(
    sidebar.getByText(/Showing locations for\s*1 shooting victim$/),
  ).toBeVisible();
  await expect(page.locator(".maplibregl-canvas")).toHaveAttribute(
    "aria-label",
    /1 fatal shooting-victim location/,
  );

  const outcomeTable = page.getByRole("table", {
    name: "Outcome distribution breakdown",
  });
  await expect(
    outcomeTable.getByRole("row", { name: "Fatal 2 100%", exact: true }),
  ).toBeAttached();
  await expect(
    outcomeTable.getByRole("row", { name: "Nonfatal 0 0%", exact: true }),
  ).toBeAttached();

  const downloadTrigger = sidebar.getByRole("button", { name: "Download Data" });
  await downloadTrigger.click();
  const dialog = page.getByRole("dialog", { name: "Download Data" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(
    "Export 2 records matching current filters",
  );
  const downloadDialogContract = await dialog.evaluate((element) => {
    const groups = Array.from(
      element.querySelectorAll<HTMLElement>(
        ".civic-dashboard-download__group",
      ),
    );
    const options = Array.from(
      element.querySelectorAll<HTMLElement>(
        ".civic-dashboard-download__option",
      ),
    );
    const hints = Array.from(
      element.querySelectorAll<HTMLElement>(
        ".civic-dashboard-download__hint",
      ),
    );
    const labels = Array.from(
      element.querySelectorAll<HTMLElement>(
        ".civic-dashboard-download__label",
      ),
    );
    const title = element.querySelector<HTMLElement>(
      ".civic-dashboard-download__header h2",
    );
    const style = getComputedStyle(element);
    const bounds = element.getBoundingClientRect();

    return {
      background: style.backgroundColor,
      borderRadius: style.borderRadius,
      groupTops: groups.map((group) => group.getBoundingClientRect().top),
      height: bounds.height,
      hintWeights: hints.map((hint) => getComputedStyle(hint).fontWeight),
      labelWeights: labels.map((label) => getComputedStyle(label).fontWeight),
      optionWeights: options.map(
        (option) => getComputedStyle(option).fontWeight,
      ),
      titleWeight: title ? getComputedStyle(title).fontWeight : null,
      width: bounds.width,
    };
  });
  expect(downloadDialogContract).toMatchObject({
    background: "rgb(45, 51, 57)",
    borderRadius: "12px",
    hintWeights: ["400", "400"],
    labelWeights: ["600", "600", "600"],
    optionWeights: ["500", "500", "500", "500"],
    titleWeight: "600",
    width: 480,
  });
  expect(downloadDialogContract.height).toBeCloseTo(577, 0);
  expect(downloadDialogContract.groupTops[1]).toBeGreaterThan(
    downloadDialogContract.groupTops[0] ?? Number.POSITIVE_INFINITY,
  );
  expect(downloadDialogContract.groupTops[2]).toBeGreaterThan(
    downloadDialogContract.groupTops[1] ?? Number.POSITIVE_INFINITY,
  );
  await dialog.locator('label[for="dashboard-download-all"]').click();
  await expect(dialog).toContainText("Export all 4 records");
  await dialog.locator('label[for="dashboard-download-csv"]').click();

  const downloadPromise = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download CSV" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(
    /^shootings-all-\d{4}-\d{2}-\d{2}\.csv$/,
  );
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  const csv = Buffer.concat(chunks).toString("utf8");
  expect(csv.trim().split("\n")).toHaveLength(5);
  expect(csv).toContain("2026-03");
  await expect(dialog).not.toBeVisible();
  await expect(downloadTrigger).toBeFocused();

  await expect(
    page.locator(".v-application, .v-overlay-container, .v-dialog, .v-btn, .v-select"),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    ),
  ).toBe(false);

  await expect
    .poll(() => apiResponses.map(({ path }) => path))
    .toEqual(
      expect.arrayContaining([
        "/shootings/meta",
        "/shootings/rows/nuxt-e2e-v1/2026.ndjson",
      ]),
    );
  expect(
    apiResponses
      .filter(({ path }) => path.startsWith("/shootings/"))
      .every(({ cors }) => cors === appOrigin),
  ).toBe(true);
});
