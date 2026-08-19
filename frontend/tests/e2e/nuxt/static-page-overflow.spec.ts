import { expect, test } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";
import {
  fullAnnualHistory,
  fullStatsSnapshot,
} from "../support/statsFixture";

const staticPages = [
  {
    heading: "Philadelphia shooting-victim and homicide statistics",
    hasTables: true,
    path: "./stats",
  },
  { heading: "Data and downloads", hasTables: true, path: "./data" },
  { heading: "Methodology", hasTables: true, path: "./methodology" },
  {
    heading: "About this dashboard",
    hasTables: false,
    path: "./about",
  },
] as const;

test.use({ viewport: { height: 812, width: 375 } });

test("reference pages keep one reading axis and contain table overflow at 375px", async ({
  page,
}) => {
  await mockNuxtExternalServices(page);

  for (const staticPage of staticPages) {
    await test.step(staticPage.path, async () => {
      await page.goto(staticPage.path);
      await expect(
        page.getByRole("heading", { level: 1, name: staticPage.heading }),
      ).toBeVisible();

      const layout = await page.evaluate(() => {
        const root = document.documentElement;
        const h1 = document.querySelector("main h1")?.getBoundingClientRect();
        const firstH2 = document.querySelector("main h2")?.getBoundingClientRect();
        const tableRegions = Array.from(
          document.querySelectorAll<HTMLElement>(
            ".usa-table-container--scrollable",
          ),
          (region) => {
            const bounds = region.getBoundingClientRect();
            const originalScrollLeft = region.scrollLeft;
            region.scrollLeft = region.scrollWidth;
            const maximumScrollLeft = region.scrollLeft;
            region.scrollLeft = originalScrollLeft;
            return {
              clientWidth: region.clientWidth,
              isTwoColumn: Boolean(
                region.querySelector("table.civic-table--two-column"),
              ),
              left: bounds.left,
              maximumScrollLeft,
              overflowX: getComputedStyle(region).overflowX,
              right: bounds.right,
              scrollWidth: region.scrollWidth,
              wrappedCellWhiteSpace: region.querySelector(".civic-table--wrap td")
                ? getComputedStyle(
                    region.querySelector<HTMLElement>(".civic-table--wrap td")!,
                  ).whiteSpace
                : null,
            };
          },
        );

        return {
          clientWidth: root.clientWidth,
          firstH2Left: firstH2?.left,
          h1Left: h1?.left,
          homicidePaddingLeft: document.querySelector(
            ".civic-current-measure--homicides",
          )
            ? getComputedStyle(
                document.querySelector<HTMLElement>(
                  ".civic-current-measure--homicides",
                )!,
              ).paddingLeft
            : null,
          introMarginBottom: document.querySelector(".civic-page-intro .usa-intro")
            ? getComputedStyle(
                document.querySelector<HTMLElement>(
                  ".civic-page-intro .usa-intro",
                )!,
              ).marginBottom
            : null,
          isReferencePage: document.querySelector("main")?.classList.contains(
            "civic-reference-page",
          ),
          scrollWidth: root.scrollWidth,
          tableRegions,
          viewportWidth: window.innerWidth,
        };
      });

      expect(layout.viewportWidth).toBe(375);
      expect(layout.clientWidth).toBe(375);
      expect(layout.scrollWidth).toBe(layout.clientWidth);
      expect(layout.isReferencePage).toBe(true);
      expect(layout.firstH2Left).toBeCloseTo(layout.h1Left ?? 0, 0);
      expect(layout.introMarginBottom).toBe("0px");
      expect(layout.tableRegions.length > 0).toBe(staticPage.hasTables);

      if (staticPage.path === "./stats") {
        expect(layout.homicidePaddingLeft).toBe("0px");
        const annualTable = page.locator("main table").filter({
          has: page.getByRole("columnheader", {
            exact: true,
            name: "Shooting victims",
          }),
        });
        await expect(annualTable).toHaveCount(1);
        await expect(
          annualTable.getByRole("columnheader", {
            exact: true,
            name: "PPD homicides",
          }),
        ).toBeVisible();

        const currentRow = annualTable.getByRole("row").filter({
          hasText: /2026\s+Year to date/i,
        });
        await expect(currentRow).toHaveCount(1);
        await expect(currentRow).toContainText("through July 28, 2026");
        await expect(currentRow).toContainText("through July 29, 2026");
        await expect(
          page.getByRole("button", { name: "Print counts by year" }),
        ).toBeVisible();
      }

      if (staticPage.path === "./data") {
        const allRecordsDownload = page.getByRole("link", {
          name: /^Download all shooting-victim records \[CSV(?:, [^\]]+)?\]$/,
        });
        await expect(allRecordsDownload).toBeVisible();
        await expect(allRecordsDownload).toHaveAttribute(
          "href",
          "https://data.example.test/philly-shooting-records/philadelphia-shooting-victims.csv",
        );
        await expect(allRecordsDownload).toHaveAttribute(
          "aria-describedby",
          "all-records-download-description",
        );
        await expect(allRecordsDownload).toHaveAccessibleDescription(
          /every available year.*one row for each person.*6 records through July 28, 2026/i,
        );
        await expect(
          page.locator(
            '[aria-labelledby="explore-download"] a[href$=".csv"]',
          ),
        ).toHaveCount(1);
        const referenceSection = page.locator(
          '[aria-labelledby="geographic-reference-downloads"]',
        );
        await expect(
          referenceSection.getByRole("heading", {
            level: 3,
            name: "Download map reference files",
          }),
        ).toBeVisible();
        await expect(
          referenceSection.getByRole("link", {
            name: /\[GEOJSON(?:, [^\]]+)?\]$/,
          }),
        ).toHaveCount(8);
        await expect(
          page.locator("main .civic-file-download-link__metadata"),
        ).toHaveCount(9);

        const downloadBounds = await allRecordsDownload.boundingBox();
        expect(downloadBounds).not.toBeNull();
        expect(downloadBounds?.x).toBeGreaterThanOrEqual(0);
        expect(
          (downloadBounds?.x ?? 0) + (downloadBounds?.width ?? 0),
        ).toBeLessThanOrEqual(375);
      }

      for (const region of layout.tableRegions) {
        expect(region.left).toBeGreaterThanOrEqual(0);
        expect(region.right).toBeLessThanOrEqual(layout.viewportWidth);
        expect(["auto", "scroll"]).toContain(region.overflowX);
        if (region.scrollWidth > region.clientWidth) {
          expect(region.maximumScrollLeft).toBeGreaterThan(0);
        }
        if (region.wrappedCellWhiteSpace !== null) {
          expect(region.wrappedCellWhiteSpace).toBe("normal");
          expect(region.scrollWidth / region.clientWidth).toBeLessThan(2);
        }
        if (region.isTwoColumn) {
          expect(region.scrollWidth).toBe(region.clientWidth);
        }
      }
    });
  }
});

test("the mobile citation block stays indented and copies its complete text", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: async (text: string) => {
          (
            window as Window & { __copiedDashboardCitation?: string }
          ).__copiedDashboardCitation = text;
        },
      },
    });
  });
  await mockNuxtExternalServices(page);
  await page.goto("./data");

  const section = page.locator('[aria-labelledby="cite-dashboard"]');
  const citation = section.locator("blockquote");
  const copyButton = section.getByRole("button", { name: "Copy citation" });
  await expect(citation).toBeVisible();
  await expect(citation).toHaveAttribute(
    "cite",
    "https://www.nickhand.dev/philly-gun-violence-map/data",
  );
  await expect(citation).toContainText(
    /Shooting-victim records through July 28, 2026.*Accessed [A-Z][a-z]+ \d{1,2}, \d{4}/,
  );
  await expect(citation).not.toContainText(/\bExample:/i);
  await expect(copyButton).toBeVisible();

  const geometry = await section.evaluate((element) => {
    const blockquote = element.querySelector("blockquote")!;
    const button = element.querySelector("button")!;
    const sectionBounds = element.getBoundingClientRect();
    const quoteBounds = blockquote.getBoundingClientRect();
    const buttonBounds = button.getBoundingClientRect();
    return {
      buttonLeft: buttonBounds.left,
      buttonRight: buttonBounds.right,
      quoteLeft: quoteBounds.left,
      quoteRight: quoteBounds.right,
      sectionLeft: sectionBounds.left,
      sectionRight: sectionBounds.right,
      pageClientWidth: document.documentElement.clientWidth,
      pageScrollWidth: document.documentElement.scrollWidth,
    };
  });
  expect(geometry.quoteLeft).toBeGreaterThan(geometry.sectionLeft);
  expect(geometry.buttonLeft).toBeGreaterThan(geometry.quoteLeft);
  expect(geometry.quoteRight).toBeLessThanOrEqual(geometry.sectionRight + 1);
  expect(geometry.buttonRight).toBeLessThanOrEqual(geometry.sectionRight + 1);
  expect(geometry.pageScrollWidth).toBe(geometry.pageClientWidth);

  const visibleCitation = (await citation.textContent())
    ?.replace(/\s+/g, " ")
    .trim();
  await expect
    .poll(() =>
      page.evaluate(() =>
        Boolean(
          (
            document.querySelector("#__nuxt") as (HTMLElement & {
              __vue_app__?: unknown;
            }) | null
          )?.__vue_app__,
        ),
      ),
    )
    .toBe(true);
  await copyButton.click();
  await expect(section.getByRole("status")).toHaveText("Citation copied.");
  const copiedCitation = await page.evaluate(
    () =>
      (window as Window & { __copiedDashboardCitation?: string })
        .__copiedDashboardCitation,
  );
  expect(copiedCitation).toBe(visibleCitation);
});

for (const viewport of [
  { height: 900, width: 1280 },
  { height: 812, width: 375 },
] as const) {
  test(`map reference download links stay inside their table cells at ${viewport.width}px`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await mockNuxtExternalServices(page);
    await page.goto("./data");

    const referenceSection = page.locator(
      '[aria-labelledby="geographic-reference-downloads"]',
    );
    const rows = referenceSection.locator("tbody tr");
    await expect(rows).toHaveCount(8);
    await expect(
      referenceSection.locator("tbody a.civic-file-download-link"),
    ).toHaveCount(8);

    const layout = await rows.evaluateAll((referenceRows) =>
      referenceRows.map((row) => {
        const rowHeader = row.querySelector<HTMLElement>('th[scope="row"]');
        const joinField = row.querySelector<HTMLElement>("td");
        const link = rowHeader?.querySelector<HTMLElement>(
          "a.civic-file-download-link",
        );
        const parts = {
          icon: link?.querySelector<HTMLElement>("svg.civic-icon"),
          label: link?.querySelector<HTMLElement>(
            ".civic-file-download-link__label",
          ),
          link,
          metadata: link?.querySelector<HTMLElement>(
            ".civic-file-download-link__metadata",
          ),
        };
        const bounds = (element: HTMLElement | null | undefined) => {
          if (!element) return null;
          const box = element.getBoundingClientRect();
          return {
            bottom: box.bottom,
            left: box.left,
            right: box.right,
            top: box.top,
          };
        };

        return {
          joinField: bounds(joinField),
          name: link?.textContent?.replace(/\s+/g, " ").trim() ?? "",
          parts: Object.fromEntries(
            Object.entries(parts).map(([name, element]) => [
              name,
              bounds(element),
            ]),
          ),
          rowHeader: bounds(rowHeader),
        };
      }),
    );

    for (const row of layout) {
      expect(row.name).toMatch(/^Download .+\[GEOJSON(?:, [^\]]+)?\]$/);
      expect(row.rowHeader).not.toBeNull();
      expect(row.joinField).not.toBeNull();
      if (!row.rowHeader || !row.joinField) continue;

      const mobileStack = viewport.width < 576;
      if (mobileStack) {
        expect(row.rowHeader.bottom).toBeLessThanOrEqual(row.joinField.top + 1);
      } else {
        expect(row.rowHeader.right).toBeLessThanOrEqual(row.joinField.left + 1);
      }
      for (const [partName, part] of Object.entries(row.parts)) {
        expect(part, `${partName} is present for ${row.name}`).not.toBeNull();
        if (!part) continue;
        expect(
          part.left,
          `${partName} stays inside the row-header left edge for ${row.name}`,
        ).toBeGreaterThanOrEqual(row.rowHeader.left - 1);
        expect(
          part.right,
          `${partName} stays inside the row-header right edge for ${row.name}`,
        ).toBeLessThanOrEqual(row.rowHeader.right + 1);
        expect(
          part.top,
          `${partName} stays inside the row-header top edge for ${row.name}`,
        ).toBeGreaterThanOrEqual(row.rowHeader.top - 1);
        expect(
          part.bottom,
          `${partName} stays inside the row-header bottom edge for ${row.name}`,
        ).toBeLessThanOrEqual(row.rowHeader.bottom + 1);
      }
    }

    const pageWidth = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(pageWidth.clientWidth).toBe(viewport.width);
    expect(pageWidth.scrollWidth).toBe(pageWidth.clientWidth);
  });
}

test("stats summaries and the annual table keep a stable 375px reading axis", async ({
  page,
}) => {
  await mockNuxtExternalServices(page);
  await page.goto("./stats");
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Philadelphia shooting-victim and homicide statistics",
    }),
  ).toBeVisible();
  await expect(page.locator(".civic-current-measure")).toHaveCount(2);
  const annualTable = page.locator("main table").filter({
    has: page.getByRole("columnheader", {
      exact: true,
      name: "Shooting victims",
    }),
  });
  await expect(annualTable).toHaveCount(1);
  await expect(annualTable.getByRole("columnheader")).toHaveText([
    "Year",
    "Shooting victims",
    "PPD homicides",
  ]);

  const geometry = await page.evaluate(() => {
    const root = document.documentElement;
    const boxStyleFor = (element: Element | null) => {
      if (!element) return null;
      const style = getComputedStyle(element);
      return {
        borderBottomWidth: style.borderBottomWidth,
        borderTopWidth: style.borderTopWidth,
        paddingTop: style.paddingTop,
      };
    };
    const boundsFor = (element: Element) => {
      const bounds = element.getBoundingClientRect();
      const htmlElement = element as HTMLElement;
      return {
        bottom: bounds.bottom,
        clientWidth: htmlElement.clientWidth,
        left: bounds.left,
        right: bounds.right,
        scrollWidth: htmlElement.scrollWidth,
        top: bounds.top,
        width: bounds.width,
      };
    };
    const measures = Array.from(
      document.querySelectorAll<HTMLElement>(".civic-current-measure"),
      boundsFor,
    );
    const hierarchy = Array.from(
      document.querySelectorAll<HTMLElement>(".civic-current-measure"),
      (measure) => {
        const heading = measure.querySelector<HTMLElement>("h2, h3");
        const total = measure.querySelector<HTMLElement>(".civic-stat-total");
        const comparison = measure.querySelector<HTMLElement>(
          ".civic-current-comparison",
        );
        const styleFor = (element: HTMLElement | null) => {
          if (!element) return null;
          const style = getComputedStyle(element);
          return {
            fontSize: style.fontSize,
            fontWeight: style.fontWeight,
            lineHeight: style.lineHeight,
          };
        };
        return {
          comparison: styleFor(comparison),
          heading: styleFor(heading),
          headingTag: heading?.tagName,
          total: styleFor(total),
        };
      },
    );
    const annualTables = Array.from(
      document.querySelectorAll<HTMLTableElement>("main table"),
    ).filter((table) => {
      const headings = Array.from(
        table.querySelectorAll("thead th"),
        (heading) => heading.textContent?.replace(/\s+/g, " ").trim(),
      );
      return (
        headings.includes("Shooting victims") &&
        headings.includes("PPD homicides")
      );
    });
    const annualRegions = annualTables.map((table) =>
      boundsFor(
        table.closest<HTMLElement>(".usa-table-container--scrollable") ?? table,
      ),
    );
    const currentGrid = document.querySelector<HTMLElement>(
      ".civic-stats-current__grid",
    );
    const containedCopy = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".civic-current-through, .civic-current-comparison, .civic-current-context",
      ),
      (element) => {
        const bounds = element.getBoundingClientRect();
        return {
          clientWidth: element.clientWidth,
          left: bounds.left,
          right: bounds.right,
          scrollWidth: element.scrollWidth,
        };
      },
    );

    return {
      annualRegions,
      clientWidth: root.clientWidth,
      containedCopy,
      currentGrid: currentGrid ? boundsFor(currentGrid) : null,
      rules: {
        currentGrid: boxStyleFor(currentGrid),
        documentation: boxStyleFor(
          document.querySelector(".civic-stats-reading-note"),
        ),
        homicideMeasure: boxStyleFor(
          document.querySelector(".civic-current-measure--homicides"),
        ),
        intro: boxStyleFor(document.querySelector(".civic-page-intro")),
      },
      hierarchy,
      measures,
      scrollWidth: root.scrollWidth,
      viewportWidth: window.innerWidth,
    };
  });

  expect(geometry.viewportWidth).toBe(375);
  expect(geometry.clientWidth).toBe(375);
  expect(geometry.scrollWidth).toBe(geometry.clientWidth);
  expect(geometry.currentGrid).not.toBeNull();
  expect(geometry.currentGrid?.scrollWidth).toBeLessThanOrEqual(
    (geometry.currentGrid?.clientWidth ?? 0) + 1,
  );
  expect(geometry.rules.intro?.borderBottomWidth).toBe("0px");
  expect(geometry.rules.currentGrid?.borderTopWidth).toBe("0px");
  expect(geometry.rules.documentation?.borderTopWidth).toBe("0px");
  expect(geometry.rules.documentation?.paddingTop).toBe("0px");
  expect(geometry.rules.homicideMeasure?.borderTopWidth).toBe("0px");
  expect(geometry.hierarchy).toHaveLength(2);
  expect(geometry.hierarchy[0].headingTag).toBe("H3");
  expect(geometry.hierarchy[1].headingTag).toBe("H3");
  expect(geometry.hierarchy[1].heading).toEqual(geometry.hierarchy[0].heading);
  expect(geometry.hierarchy[1].total).toEqual(geometry.hierarchy[0].total);
  expect(geometry.hierarchy[1].comparison).toEqual(
    geometry.hierarchy[0].comparison,
  );

  expect(geometry.measures).toHaveLength(2);
  expect(geometry.measures[1].left).toBeCloseTo(geometry.measures[0].left, 0);
  expect(geometry.measures[1].width).toBeCloseTo(geometry.measures[0].width, 0);
  expect(geometry.measures[1].top).toBeGreaterThan(
    geometry.measures[0].bottom + 8,
  );
  for (const item of geometry.measures) {
    expect(item.left).toBeGreaterThanOrEqual(0);
    expect(item.right).toBeLessThanOrEqual(geometry.viewportWidth);
    expect(item.scrollWidth).toBeLessThanOrEqual(item.clientWidth + 1);
  }

  expect(geometry.annualRegions).toHaveLength(1);
  for (const region of geometry.annualRegions) {
    expect(region.left).toBeGreaterThanOrEqual(0);
    expect(region.right).toBeLessThanOrEqual(geometry.viewportWidth);
  }

  expect(geometry.containedCopy.length).toBeGreaterThanOrEqual(5);
  for (const item of geometry.containedCopy) {
    expect(item.left).toBeGreaterThanOrEqual(0);
    expect(item.right).toBeLessThanOrEqual(geometry.viewportWidth);
    expect(item.scrollWidth).toBeLessThanOrEqual(item.clientWidth + 1);
  }
});

test("stats prints its annual counts on one portrait page", async ({ page }) => {
  await mockNuxtExternalServices(page);
  await page.route("http://127.0.0.1:4181/stats.json", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify(fullStatsSnapshot),
    }),
  );
  await page.goto("./about");
  await page.waitForFunction(() =>
    Boolean(
      (
        document.querySelector("#__nuxt") as (Element & {
          __vue_app__?: unknown;
        }) | null
      )?.__vue_app__,
    ),
  );
  await page
    .getByRole("link", { exact: true, name: "statistics page" })
    .click();
  await expect(page).toHaveURL(/\/stats$/);
  await page.evaluate(() => {
    window.print = () => {
      document.documentElement.dataset.statsPrintInvoked = "true";
    };
  });

  const printButton = page.getByRole("button", {
    name: "Print counts by year",
  });
  await expect(printButton).toHaveAttribute("title", "Print counts by year");
  await expect(printButton.locator(".civic-print-button__label")).toHaveCSS(
    "display",
    "none",
  );
  await printButton.click();
  await expect(page.locator("html")).toHaveAttribute(
    "data-stats-print-invoked",
    "true",
  );

  await page.emulateMedia({ media: "print" });
  const annualTable = page.locator("main table").filter({
    has: page.getByRole("columnheader", {
      exact: true,
      name: "Shooting victims",
    }),
  });
  await expect(annualTable).toBeVisible();
  await expect(annualTable.locator("tbody tr")).toHaveCount(
    fullAnnualHistory.length,
  );
  await expect(annualTable.locator("tbody th > span:first-child")).toHaveText(
    fullAnnualHistory.map(({ year }) => String(year)),
  );
  await expect(page.locator(".civic-stats-current")).toBeHidden();
  const annualSources = page.locator(".civic-annual-source");
  await expect(annualSources).toHaveCount(2);
  await expect(annualSources).toHaveText([
    /Shooting victims:\s*Philadelphia Police Department shooting-victim records via OpenDataPhilly\./,
    /Homicides:\s*Philadelphia Police Department homicide statistics\./,
  ]);
  await expect(annualSources.nth(0)).toBeVisible();
  await expect(annualSources.nth(1)).toBeVisible();
  await expect(printButton).toBeHidden();

  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  const printGeometry = await page.evaluate(() => {
    const annualSeries = document.querySelector<HTMLElement>(
      ".civic-annual-series",
    );
    const region = document.querySelector<HTMLElement>(
      ".civic-annual-series .civic-table-region",
    );
    const table = document.querySelector<HTMLTableElement>(
      ".civic-annual-table",
    );
    const sources = Array.from(
      document.querySelectorAll<HTMLElement>(".civic-annual-source"),
      (source) => {
        const bounds = source.getBoundingClientRect();
        const style = getComputedStyle(source);
        return {
          bottom: bounds.bottom,
          display: style.display,
          height: bounds.height,
          left: bounds.left,
          right: bounds.right,
          visibility: style.visibility,
        };
      },
    );
    const seriesBounds = annualSeries?.getBoundingClientRect();
    const tableBounds = table?.getBoundingClientRect();
    const appShell = document.querySelector<HTMLElement>(".civic-app-shell");
    const appShellStyle = appShell ? getComputedStyle(appShell) : null;
    const main = appShell?.querySelector<HTMLElement>(":scope > main") ?? null;
    const mainStyle = main ? getComputedStyle(main) : null;

    return {
      appShell: appShellStyle
        ? {
            display: appShellStyle.display,
            minHeight: appShellStyle.minHeight,
          }
        : null,
      annualSeries: annualSeries
        ? {
            clientWidth: annualSeries.clientWidth,
            scrollWidth: annualSeries.scrollWidth,
          }
        : null,
      printableHeight: 10 * 96,
      main: mainStyle ? { flexGrow: mainStyle.flexGrow } : null,
      region: region
        ? {
            clientWidth: region.clientWidth,
            overflowX: getComputedStyle(region).overflowX,
            scrollWidth: region.scrollWidth,
          }
        : null,
      root: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      },
      seriesBounds: seriesBounds
        ? { left: seriesBounds.left, right: seriesBounds.right }
        : null,
      sources,
      tableBounds: tableBounds
        ? { left: tableBounds.left, right: tableBounds.right }
        : null,
    };
  });

  expect(printGeometry.root.clientWidth).toBe(375);
  expect(printGeometry.root.scrollWidth).toBeLessThanOrEqual(376);
  expect(printGeometry.appShell).toEqual({ display: "block", minHeight: "0px" });
  expect(printGeometry.main?.flexGrow).toBe("0");
  expect(printGeometry.annualSeries).not.toBeNull();
  expect(printGeometry.annualSeries?.scrollWidth).toBeLessThanOrEqual(
    (printGeometry.annualSeries?.clientWidth ?? 0) + 1,
  );
  expect(printGeometry.region).not.toBeNull();
  expect(printGeometry.region?.overflowX).toBe("visible");
  expect(printGeometry.region?.scrollWidth).toBeLessThanOrEqual(
    (printGeometry.region?.clientWidth ?? 0) + 1,
  );
  expect(printGeometry.tableBounds?.left ?? -1).toBeGreaterThanOrEqual(
    printGeometry.seriesBounds?.left ?? 0,
  );
  expect(
    printGeometry.tableBounds?.right ?? Number.POSITIVE_INFINITY,
  ).toBeLessThanOrEqual((printGeometry.seriesBounds?.right ?? 0) + 1);
  expect(printGeometry.sources).toHaveLength(2);
  for (const source of printGeometry.sources) {
    expect(source.display).not.toBe("none");
    expect(source.visibility).toBe("visible");
    expect(source.height).toBeGreaterThan(0);
    expect(source.left).toBeGreaterThanOrEqual(
      printGeometry.seriesBounds?.left ?? 0,
    );
    expect(source.right).toBeLessThanOrEqual(
      (printGeometry.seriesBounds?.right ?? 0) + 1,
    );
    expect(source.bottom).toBeLessThanOrEqual(printGeometry.printableHeight + 1);
  }

  const pdf = await page.pdf({
    displayHeaderFooter: true,
    preferCSSPageSize: true,
    printBackground: true,
    tagged: false,
  });
  const pdfSource = pdf.toString("latin1");
  expect(pdfSource.match(/\/Type\s*\/Page\b/g)).toHaveLength(1);

  const mediaBoxes = [
    ...pdfSource.matchAll(/\/MediaBox\s*\[\s*0\s+0\s+(\d+)\s+(\d+)\s*\]/g),
  ].map(([, width, height]) => ({
    height: Number(height),
    width: Number(width),
  }));
  expect(mediaBoxes).toHaveLength(1);
  expect(mediaBoxes[0].width).toBeLessThan(mediaBoxes[0].height);
});

test("annual title action and current-year dates stay aligned with their columns", async ({
  page,
}) => {
  await page.setViewportSize({ height: 900, width: 1440 });
  await mockNuxtExternalServices(page);
  await page.goto("./stats");

  const desktop = await page.evaluate(() => {
    const boundsFor = (selector: string) => {
      const element = document.querySelector<HTMLElement>(selector);
      if (!element) return null;
      const bounds = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return {
        bottom: bounds.bottom,
        contentLeft: bounds.left + parseFloat(style.paddingLeft || "0"),
        contentRight: bounds.right - parseFloat(style.paddingRight || "0"),
        left: bounds.left,
        right: bounds.right,
        textAlign: style.textAlign,
        top: bounds.top,
        verticalCenter: bounds.top + bounds.height / 2,
      };
    };

    const currentMeasures = Array.from(
      document.querySelectorAll<HTMLElement>(".civic-current-measure"),
      (measure) => {
        const bounds = measure.getBoundingClientRect();
        const style = getComputedStyle(measure);
        const heading = measure
          .querySelector<HTMLElement>(":scope > h3")
          ?.getBoundingClientRect();
        return {
          gridTemplateRows: style.gridTemplateRows,
          headingTop: heading?.top ?? null,
          left: bounds.left,
          right: bounds.right,
          top: bounds.top,
          width: bounds.width,
        };
      },
    );

    return {
      currentMeasures,
      homicideCell: boundsFor(
        ".civic-annual-row--current td.civic-annual-homicides",
      ),
      homicideDate: boundsFor(
        ".civic-annual-row--current .civic-annual-current-date--homicides",
      ),
      homicideHeader: boundsFor(
        ".civic-annual-table thead th:nth-child(3)",
      ),
      printButton: boundsFor(
        ".civic-annual-heading__title-row .civic-print-button",
      ),
      title: boundsFor(".civic-annual-heading__title-row #counts-by-year"),
      victimsCell: boundsFor(
        ".civic-annual-row--current td.civic-annual-victims",
      ),
      victimsDate: boundsFor(
        ".civic-annual-row--current .civic-annual-current-date--victims",
      ),
      victimsHeader: boundsFor(
        ".civic-annual-table thead th:nth-child(2)",
      ),
    };
  });

  expect(desktop.title).not.toBeNull();
  expect(desktop.printButton).not.toBeNull();
  expect(desktop.title?.verticalCenter).toBeCloseTo(
    desktop.printButton?.verticalCenter ?? 0,
    0,
  );
  expect(desktop.printButton?.left ?? 0).toBeGreaterThan(
    desktop.title?.right ?? 0,
  );

  expect(desktop.currentMeasures).toHaveLength(2);
  expect(desktop.currentMeasures[0].width).toBeCloseTo(
    desktop.currentMeasures[1].width,
    0,
  );
  expect(desktop.currentMeasures[0].top).toBeCloseTo(
    desktop.currentMeasures[1].top,
    0,
  );
  expect(desktop.currentMeasures[0].headingTop).not.toBeNull();
  expect(desktop.currentMeasures[1].headingTop).not.toBeNull();
  expect(desktop.currentMeasures[0].headingTop ?? 0).toBeCloseTo(
    desktop.currentMeasures[1].headingTop ?? 0,
    0,
  );
  expect(desktop.currentMeasures[0].right).toBeLessThanOrEqual(
    desktop.currentMeasures[1].left,
  );
  for (const measure of desktop.currentMeasures) {
    expect(measure.gridTemplateRows).not.toContain("subgrid");
  }

  expect(desktop.victimsCell).not.toBeNull();
  expect(desktop.victimsDate).not.toBeNull();
  expect(desktop.victimsDate?.left).toBeCloseTo(
    desktop.victimsCell?.contentLeft ?? 0,
    0,
  );
  expect(desktop.victimsDate?.left).toBeCloseTo(
    desktop.victimsHeader?.contentLeft ?? 0,
    0,
  );
  expect(desktop.victimsDate?.textAlign).toBe("left");
  expect(desktop.victimsDate?.left ?? 0).toBeGreaterThanOrEqual(
    desktop.victimsCell?.left ?? 0,
  );
  expect(desktop.victimsDate?.right ?? 0).toBeLessThanOrEqual(
    (desktop.victimsCell?.right ?? 0) + 1,
  );

  expect(desktop.homicideCell).not.toBeNull();
  expect(desktop.homicideDate).not.toBeNull();
  expect(desktop.homicideDate?.right).toBeCloseTo(
    desktop.homicideCell?.contentRight ?? 0,
    0,
  );
  expect(desktop.homicideDate?.right).toBeCloseTo(
    desktop.homicideHeader?.contentRight ?? 0,
    0,
  );
  expect(desktop.homicideDate?.textAlign).toBe("right");
  expect(desktop.homicideDate?.left ?? 0).toBeGreaterThanOrEqual(
    desktop.homicideCell?.left ?? 0,
  );
  expect(desktop.homicideDate?.right ?? 0).toBeLessThanOrEqual(
    (desktop.homicideCell?.right ?? 0) + 1,
  );
  expect(desktop.victimsDate?.top).toBeCloseTo(
    desktop.homicideDate?.top ?? 0,
    0,
  );

  await page.setViewportSize({ height: 812, width: 375 });
  const mobileTitle = await page.evaluate(() => {
    const titleElement = document.querySelector<HTMLElement>(
      ".civic-annual-heading__title-row #counts-by-year",
    );
    const buttonElement = document.querySelector<HTMLElement>(
      ".civic-annual-heading__title-row .civic-print-button",
    );
    const labelElement = buttonElement?.querySelector<HTMLElement>(
      ".civic-print-button__label",
    );
    const title = titleElement?.getBoundingClientRect();
    const button = buttonElement?.getBoundingClientRect();
    return title && button
      ? {
          buttonLeft: button.left,
          buttonWidth: button.width,
          labelDisplay: labelElement
            ? getComputedStyle(labelElement).display
            : null,
          titleRight: title.right,
          verticalCenterDifference: Math.abs(
            title.top + title.height / 2 - (button.top + button.height / 2),
          ),
        }
      : null;
  });
  expect(mobileTitle).not.toBeNull();
  expect(mobileTitle?.buttonLeft ?? 0).toBeGreaterThan(
    mobileTitle?.titleRight ?? 0,
  );
  expect(mobileTitle?.buttonWidth).toBeCloseTo(44, 0);
  expect(mobileTitle?.labelDisplay).toBe("none");
  expect(
    mobileTitle?.verticalCenterDifference ?? Number.POSITIVE_INFINITY,
  ).toBeLessThanOrEqual(1);
});
