import { expect, test } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";

const mobileViewports = [
  { height: 720, width: 320 },
  { height: 812, width: 375 },
  { height: 844, width: 390 },
  { height: 932, width: 430 },
] as const;

test("keeps data-table identifiers intact and rows contained on narrow screens", async ({
  page,
}) => {
  await mockNuxtExternalServices(page);
  await page.goto("./data");
  await expect(
    page.getByRole("heading", { level: 1, name: "Data and downloads" }),
  ).toBeVisible();

  for (const viewport of mobileViewports) {
    await test.step(`${viewport.width}px`, async () => {
      await page.setViewportSize(viewport);
      await page.evaluate(
        () =>
          new Promise<void>((resolve) => {
            requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
          }),
      );

      const fieldGuideTable = page.getByRole("table", {
        name: "Key fields in record-level downloads",
      });
      const referenceTable = page.getByRole("table", {
        name: "Map reference downloads and their matching record fields",
      });
      const sourceTable = page.getByRole("table", {
        name: "Public sources and dates used by this dashboard",
      });
      await expect(fieldGuideTable.getByRole("columnheader")).toHaveCount(2);
      await expect(fieldGuideTable.getByRole("rowheader")).toHaveCount(9);
      await expect(referenceTable.getByRole("columnheader")).toHaveCount(2);
      await expect(referenceTable.getByRole("rowheader")).toHaveCount(8);
      await expect(sourceTable.getByRole("columnheader")).toHaveCount(3);
      await expect(sourceTable.getByRole("rowheader")).toHaveCount(3);
      await expect(sourceTable).toContainText("Records through July 28, 2026");

      const geometry = await page.evaluate(() => {
        const boundsFor = (element: Element) => {
          const bounds = element.getBoundingClientRect();
          return {
            bottom: bounds.bottom,
            height: bounds.height,
            left: bounds.left,
            right: bounds.right,
            top: bounds.top,
            width: bounds.width,
          };
        };
        const tableRegions = [
          {
            name: "Field guide",
            selector:
              '.usa-table-container--scrollable[aria-labelledby="record-fields"]',
          },
          {
            name: "Map reference files",
            selector:
              '.usa-table-container--scrollable[aria-labelledby="geographic-reference-downloads"]',
          },
        ].map(({ name, selector }) => {
          const region = document.querySelector<HTMLElement>(selector);
          if (!region) return { name, region: null, rows: [] };

          const rows = Array.from(
            region.querySelectorAll<HTMLTableRowElement>("tbody tr"),
            (row) => {
              const rowHeader = row.querySelector<HTMLTableCellElement>(
                'th[scope="row"]',
              );
              const valueCell = row.querySelector<HTMLTableCellElement>("td");
              const codeTokens = Array.from(
                row.querySelectorAll<HTMLElement>("code"),
                (code) => {
                  const range = document.createRange();
                  range.selectNodeContents(code);
                  const fragments = Array.from(
                    range.getClientRects(),
                    (fragment) => ({
                      bottom: fragment.bottom,
                      left: fragment.left,
                      right: fragment.right,
                      top: fragment.top,
                      width: fragment.width,
                    }),
                  ).filter((fragment) => fragment.width > 0.5);

                  return {
                    bounds: boundsFor(code),
                    fragments,
                    text: code.textContent?.trim() ?? "",
                  };
                },
              );

              return {
                bounds: boundsFor(row),
                codeTokens,
                rowHeader: rowHeader ? boundsFor(rowHeader) : null,
                valueCell: valueCell ? boundsFor(valueCell) : null,
              };
            },
          );

          return {
            name,
            region: {
              bounds: boundsFor(region),
              clientWidth: region.clientWidth,
              scrollWidth: region.scrollWidth,
            },
            rows,
          };
        });
        const root = document.documentElement;

        return {
          clientWidth: root.clientWidth,
          scrollWidth: root.scrollWidth,
          tableRegions,
          viewportWidth: window.innerWidth,
        };
      });

      expect(geometry.viewportWidth).toBe(viewport.width);
      expect(geometry.clientWidth).toBe(viewport.width);
      expect(geometry.scrollWidth).toBe(geometry.clientWidth);

      for (const table of geometry.tableRegions) {
        expect(table.region, `${table.name} region is present`).not.toBeNull();
        if (!table.region) continue;

        expect(table.region.bounds.left).toBeGreaterThanOrEqual(0);
        expect(table.region.bounds.right).toBeLessThanOrEqual(
          viewport.width + 1,
        );
        expect(table.region.scrollWidth).toBeLessThanOrEqual(
          table.region.clientWidth + 1,
        );
        expect(table.rows.length, `${table.name} has data rows`).toBeGreaterThan(
          0,
        );

        for (const row of table.rows) {
          expect(row.rowHeader).not.toBeNull();
          expect(row.valueCell).not.toBeNull();
          if (!row.rowHeader || !row.valueCell) continue;

          for (const cell of [row.rowHeader, row.valueCell]) {
            expect(cell.left).toBeGreaterThanOrEqual(
              table.region.bounds.left - 1,
            );
            expect(cell.right).toBeLessThanOrEqual(
              table.region.bounds.right + 1,
            );
            expect(cell.width).toBeGreaterThanOrEqual(
              table.region.clientWidth - 1,
            );
            expect(cell.top).toBeGreaterThanOrEqual(row.bounds.top - 1);
            expect(cell.bottom).toBeLessThanOrEqual(row.bounds.bottom + 1);
          }

          const separatedHorizontally =
            row.rowHeader.right <= row.valueCell.left + 1 ||
            row.valueCell.right <= row.rowHeader.left + 1;
          const separatedVertically =
            row.rowHeader.bottom <= row.valueCell.top + 1 ||
            row.valueCell.bottom <= row.rowHeader.top + 1;
          expect(
            separatedHorizontally || separatedVertically,
            `${table.name} row cells do not overlap`,
          ).toBe(true);

          for (const token of row.codeTokens) {
            expect(token.text, `${table.name} code token is not empty`).not.toBe(
              "",
            );
            expect(
              token.fragments,
              `${token.text} remains one unbroken identifier at ${viewport.width}px`,
            ).toHaveLength(1);
            expect(token.bounds.left).toBeGreaterThanOrEqual(
              table.region.bounds.left - 1,
            );
            expect(token.bounds.right).toBeLessThanOrEqual(
              table.region.bounds.right + 1,
            );
          }
        }
      }

      const responsiveControls = await page.evaluate(() => {
        const boundsFor = (element: Element) => {
          const bounds = element.getBoundingClientRect();
          return {
            bottom: bounds.bottom,
            height: bounds.height,
            left: bounds.left,
            right: bounds.right,
            top: bounds.top,
            width: bounds.width,
          };
        };
        const sourceRegion = document.querySelector<HTMLElement>(
          '.usa-table-container--scrollable[aria-labelledby="source-records"]',
        );
        const sourceRows = sourceRegion
          ? Array.from(
              sourceRegion.querySelectorAll<HTMLTableRowElement>("tbody tr"),
              (row) => ({
                bounds: boundsFor(row),
                cells: Array.from(row.children, (cell) => boundsFor(cell)),
                labels: Array.from(
                  row.querySelectorAll<HTMLElement>(
                    ".civic-data-stacked-table__label",
                  ),
                  (label) => ({
                    bounds: boundsFor(label),
                    display: getComputedStyle(label).display,
                    text: label.textContent?.trim() ?? "",
                  }),
                ),
              }),
            )
          : [];
        const download = document.querySelector<HTMLElement>(
          '[aria-labelledby="explore-download"] .civic-file-download-link--button',
        );
        const downloadLabel = download?.querySelector<HTMLElement>(
          ".civic-file-download-link__label",
        );
        const downloadMetadata = download?.querySelector<HTMLElement>(
          ".civic-file-download-link__metadata",
        );

        return {
          download: download
            ? {
                bounds: boundsFor(download),
                display: getComputedStyle(download).display,
                label: downloadLabel ? boundsFor(downloadLabel) : null,
                metadata: downloadMetadata ? boundsFor(downloadMetadata) : null,
                visibleLabel: Array.from(
                  downloadLabel?.childNodes ?? [],
                  (node) => (node.nodeType === Node.TEXT_NODE ? node.textContent : ""),
                )
                  .join(" ")
                  .replace(/\s+/g, " ")
                  .trim(),
              }
            : null,
          sourceRegion: sourceRegion
            ? {
                bounds: boundsFor(sourceRegion),
                clientWidth: sourceRegion.clientWidth,
                scrollWidth: sourceRegion.scrollWidth,
              }
            : null,
          sourceRows,
        };
      });

      expect(responsiveControls.sourceRegion).not.toBeNull();
      if (responsiveControls.sourceRegion) {
        expect(responsiveControls.sourceRegion.scrollWidth).toBeLessThanOrEqual(
          responsiveControls.sourceRegion.clientWidth + 1,
        );
        expect(responsiveControls.sourceRows).toHaveLength(3);
        for (const row of responsiveControls.sourceRows) {
          expect(row.cells).toHaveLength(3);
          expect(row.labels.map((label) => label.text)).toEqual([
            "Source:",
            "How it is used:",
            "Dates in this dashboard:",
          ]);
          for (const label of row.labels) {
            expect(label.display).toBe("inline");
            expect(label.bounds.left).toBeGreaterThanOrEqual(
              responsiveControls.sourceRegion.bounds.left - 1,
            );
            expect(label.bounds.right).toBeLessThanOrEqual(
              responsiveControls.sourceRegion.bounds.right + 1,
            );
          }
          for (const cell of row.cells) {
            expect(cell.left).toBeGreaterThanOrEqual(
              responsiveControls.sourceRegion.bounds.left - 1,
            );
            expect(cell.right).toBeLessThanOrEqual(
              responsiveControls.sourceRegion.bounds.right + 1,
            );
            expect(cell.width).toBeGreaterThanOrEqual(
              responsiveControls.sourceRegion.clientWidth - 1,
            );
            expect(cell.top).toBeGreaterThanOrEqual(row.bounds.top - 1);
            expect(cell.bottom).toBeLessThanOrEqual(row.bounds.bottom + 1);
          }
          for (let index = 1; index < row.cells.length; index += 1) {
            expect(row.cells[index]!.top).toBeGreaterThanOrEqual(
              row.cells[index - 1]!.bottom - 1,
            );
          }
        }
      }

      expect(responsiveControls.download).not.toBeNull();
      if (responsiveControls.download) {
        expect(responsiveControls.download.display).toBe("inline-grid");
        expect(responsiveControls.download.visibleLabel).toBe(
          "Download all records",
        );
        expect(responsiveControls.download.bounds.left).toBeGreaterThanOrEqual(0);
        expect(responsiveControls.download.bounds.right).toBeLessThanOrEqual(
          viewport.width + 1,
        );
        expect(responsiveControls.download.bounds.height).toBeLessThanOrEqual(80);
        expect(responsiveControls.download.label).not.toBeNull();
        expect(responsiveControls.download.metadata).not.toBeNull();
        if (
          responsiveControls.download.label &&
          responsiveControls.download.metadata
        ) {
          expect(responsiveControls.download.label.right).toBeLessThanOrEqual(
            responsiveControls.download.metadata.left + 1,
          );
          expect(responsiveControls.download.label.bottom).toBeLessThanOrEqual(
            responsiveControls.download.bounds.bottom + 1,
          );
          expect(responsiveControls.download.metadata.right).toBeLessThanOrEqual(
            responsiveControls.download.bounds.right + 1,
          );
        }
      }
    });
  }
});

test("gives every chart-info control a 44-pixel target without crowding mobile cards", async ({
  page,
}) => {
  await mockNuxtExternalServices(page);
  await page.goto("./");
  await expect(page.locator(".civic-dashboard-browser-explorer")).toHaveAttribute(
    "aria-busy",
    "false",
  );

  for (const viewport of mobileViewports) {
    await test.step(`${viewport.width}px`, async () => {
      await page.setViewportSize(viewport);
      await page.evaluate(
        () =>
          new Promise<void>((resolve) => {
            requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
          }),
      );

      const triggers = page.locator(
        "[data-chart-definition] .civic-info-tooltip__trigger",
      );
      await expect(triggers).toHaveCount(5);
      const geometry = await page.evaluate(() => {
        const root = document.documentElement;
        return {
          clientWidth: root.clientWidth,
          scrollWidth: root.scrollWidth,
          triggers: Array.from(
            document.querySelectorAll<HTMLElement>(
              "[data-chart-definition] .civic-info-tooltip__trigger",
            ),
            (trigger) => {
              const bounds = trigger.getBoundingClientRect();
              const glyph = trigger.querySelector<HTMLElement>(
                ".civic-info-tooltip__glyph",
              );
              const glyphBounds = glyph?.getBoundingClientRect();
              const card = trigger.closest<HTMLElement>(
                ".civic-dashboard-category-chart",
              );
              const cardBounds = card?.getBoundingClientRect();
              return {
                bottom: bounds.bottom,
                cardBottom: cardBounds?.bottom ?? Number.NaN,
                cardLeft: cardBounds?.left ?? Number.NaN,
                cardRight: cardBounds?.right ?? Number.NaN,
                cardTop: cardBounds?.top ?? Number.NaN,
                glyphHeight: glyphBounds?.height ?? Number.NaN,
                glyphWidth: glyphBounds?.width ?? Number.NaN,
                height: bounds.height,
                left: bounds.left,
                right: bounds.right,
                top: bounds.top,
                width: bounds.width,
              };
            },
          ),
        };
      });

      expect(geometry.clientWidth).toBe(viewport.width);
      expect(geometry.scrollWidth).toBe(geometry.clientWidth);
      for (const trigger of geometry.triggers) {
        expect(trigger.width).toBeGreaterThanOrEqual(44);
        expect(trigger.height).toBeGreaterThanOrEqual(44);
        expect(trigger.glyphWidth).toBeCloseTo(24, 0);
        expect(trigger.glyphHeight).toBeCloseTo(24, 0);
        expect(trigger.left).toBeGreaterThanOrEqual(trigger.cardLeft - 1);
        expect(trigger.right).toBeLessThanOrEqual(trigger.cardRight + 1);
        expect(trigger.top).toBeGreaterThanOrEqual(trigger.cardTop - 1);
        expect(trigger.bottom).toBeLessThanOrEqual(trigger.cardBottom + 1);
      }

      const outcomeCard = page.locator(
        ".civic-dashboard-category-chart--outcome",
      );
      const initialHeight = await outcomeCard.evaluate(
        (element) => element.getBoundingClientRect().height,
      );
      await outcomeCard
        .getByRole("button", { name: "About Outcome" })
        .click();
      const tooltip = outcomeCard.locator(".civic-info-tooltip__panel");
      await expect(tooltip).toBeVisible();
      await expect(tooltip).toHaveAttribute("role", "dialog");
      const openHeight = await outcomeCard.evaluate(
        (element) => element.getBoundingClientRect().height,
      );
      expect(openHeight).toBeCloseTo(initialHeight, 1);
      const tooltipBounds = await tooltip.boundingBox();
      expect(tooltipBounds).not.toBeNull();
      expect(tooltipBounds?.x).toBeGreaterThanOrEqual(0);
      expect(
        (tooltipBounds?.x ?? 0) + (tooltipBounds?.width ?? 0),
      ).toBeLessThanOrEqual(viewport.width + 1);
      await outcomeCard
        .getByRole("button", { name: "Close Outcome information" })
        .click();
      await expect(tooltip).not.toBeVisible();
    });
  }
});
