import { expect, test } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";
import {
  fullAnnualHistory,
  fullStatsSnapshot,
} from "../support/statsFixture";

test("stats shooting-victim bars stay visible and proportional at narrow mobile widths", async ({
  page,
}) => {
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
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Philadelphia shooting-victim and homicide statistics",
    }),
  ).toBeVisible();

  const bars = page.locator(".civic-annual-victims .civic-annual-bar");
  await expect(bars).toHaveCount(fullAnnualHistory.length);

  for (const viewport of [
    { height: 720, width: 320 },
    { height: 812, width: 375 },
    { height: 844, width: 390 },
    { height: 932, width: 430 },
  ] as const) {
    await test.step(`${viewport.width}px`, async () => {
      await page.setViewportSize(viewport);
      await page.evaluate(
        () =>
          new Promise<void>((resolve) => {
            requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
          }),
      );

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
        const table = document.querySelector<HTMLTableElement>(
          ".civic-annual-table",
        );
        const tableBounds = table ? boundsFor(table) : null;
        const rows = Array.from(
          document.querySelectorAll<HTMLTableRowElement>(
            ".civic-annual-table tbody tr",
          ),
          (row) => {
            const cell = row.querySelector<HTMLTableCellElement>(
              ".civic-annual-victims",
            );
            const plot = cell?.querySelector<HTMLElement>(
              ".civic-annual-bar-plot",
            );
            const bar = plot?.querySelector<HTMLElement>(
              ".civic-annual-bar",
            );
            const value = Number.parseInt(
              cell
                ?.querySelector(".civic-annual-value")
                ?.textContent?.replace(/\D/g, "") ?? "",
              10,
            );
            const plotStyle = plot ? getComputedStyle(plot) : null;
            const barStyle = bar ? getComputedStyle(bar) : null;

            return {
              bar: bar ? boundsFor(bar) : null,
              barDisplay: barStyle?.display ?? null,
              barVisibility: barStyle?.visibility ?? null,
              cell: cell ? boundsFor(cell) : null,
              plot: plot ? boundsFor(plot) : null,
              plotDisplay: plotStyle?.display ?? null,
              plotVisibility: plotStyle?.visibility ?? null,
              value,
            };
          },
        );
        const root = document.documentElement;

        return {
          clientWidth: root.clientWidth,
          rows,
          scrollWidth: root.scrollWidth,
          table: tableBounds,
          viewportWidth: window.innerWidth,
        };
      });

      expect(geometry.viewportWidth).toBe(viewport.width);
      expect(geometry.clientWidth).toBe(viewport.width);
      expect(geometry.scrollWidth).toBe(geometry.clientWidth);
      expect(geometry.table).not.toBeNull();
      expect(geometry.table?.left).toBeGreaterThanOrEqual(0);
      expect(geometry.table?.right).toBeLessThanOrEqual(viewport.width + 1);
      expect(geometry.rows).toHaveLength(fullAnnualHistory.length);

      const peak = Math.max(...geometry.rows.map(({ value }) => value));
      for (const row of geometry.rows) {
        expect(row.value).toBeGreaterThan(0);
        expect(row.cell).not.toBeNull();
        expect(row.plot).not.toBeNull();
        expect(row.bar).not.toBeNull();
        expect(row.plotDisplay).not.toBe("none");
        expect(row.plotVisibility).toBe("visible");
        expect(row.barDisplay).not.toBe("none");
        expect(row.barVisibility).toBe("visible");
        if (!row.cell || !row.plot || !row.bar || !geometry.table) continue;

        expect(row.plot.width).toBeGreaterThan(0);
        expect(row.plot.height).toBeGreaterThan(0);
        expect(row.bar.width).toBeGreaterThan(0);
        expect(row.bar.height).toBeGreaterThan(0);
        expect(row.plot.left).toBeGreaterThanOrEqual(row.cell.left - 1);
        expect(row.plot.right).toBeLessThanOrEqual(row.cell.right + 1);
        expect(row.bar.left).toBeGreaterThanOrEqual(row.plot.left - 1);
        expect(row.bar.right).toBeLessThanOrEqual(row.plot.right + 1);
        expect(row.bar.left).toBeGreaterThanOrEqual(geometry.table.left - 1);
        expect(row.bar.right).toBeLessThanOrEqual(geometry.table.right + 1);

        const renderedProportion = row.bar.width / row.plot.width;
        const expectedProportion = row.value / peak;
        expect(Math.abs(renderedProportion - expectedProportion)).toBeLessThan(
          0.015,
        );
      }
    });
  }
});
