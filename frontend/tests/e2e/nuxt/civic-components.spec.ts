import { expect, test } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";

// Keep this title free of "print": the WebKit project excludes PDF-only tests
// by title, while this layout-only regression must run there.
test("keeps a portrait map snapshot inside its one-page sheet", async ({
  page,
}) => {
  await page.setViewportSize({ height: 960, width: 720 });
  await mockNuxtExternalServices(page);
  await page.goto("./about");
  await page.evaluate(async () => {
    const canvas = document.createElement("canvas");
    canvas.width = 390;
    canvas.height = 844;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas 2D context is unavailable");
    context.fillStyle = "#202a2f";
    context.fillRect(0, 0, canvas.width, canvas.height);

    const sheet = document.createElement("section");
    sheet.className = "civic-dashboard-map-print-sheet";
    sheet.setAttribute("aria-label", "Printable map fixture");
    sheet.innerHTML = `
      <header>
        <p>Philadelphia Gun Violence Dashboard</p>
        <h1>Philadelphia shooting-victim map — 2026</h1>
        <p>Shooting-victim locations for 440 of 442 shooting-victim records in 2026.</p>
      </header>
      <img alt="Portrait map fixture" src="${canvas.toDataURL("image/png")}">
      <div class="civic-dashboard-map-print-sheet__legend">
        <ul>
          <li><span class="civic-dashboard-map-print-sheet__marker--fatal"></span>Fatal — 94</li>
          <li><span class="civic-dashboard-map-print-sheet__marker--nonfatal"></span>Nonfatal — 348</li>
        </ul>
      </div>
      <footer>
        <p>Shooting-victim records: Philadelphia Police Department via OpenDataPhilly.</p>
        <p>Sources: Esri, HERE, Garmin, FAO, NOAA, USGS, © OpenStreetMap contributors, and the GIS User Community.</p>
      </footer>
    `;
    document.documentElement.classList.add(
      "civic-dashboard-map-print-active",
    );
    document.body.classList.add("civic-dashboard-map-print-active");
    document.body.append(sheet);

    const image = sheet.querySelector("img");
    if (!image) throw new Error("Map fixture image was not created");
    await image.decode();
    await document.fonts.ready;
  });
  await page.emulateMedia({ media: "print" });

  const geometry = await page
    .locator(".civic-dashboard-map-print-sheet")
    .evaluate((sheet) => {
      const bounds = (selector: string) => {
        const element = sheet.querySelector<HTMLElement>(selector);
        if (!element) return null;
        const rect = element.getBoundingClientRect();
        return {
          bottom: rect.bottom,
          height: rect.height,
          left: rect.left,
          right: rect.right,
          top: rect.top,
          width: rect.width,
        };
      };
      const rect = sheet.getBoundingClientRect();
      const image = sheet.querySelector<HTMLImageElement>("img");
      const imageStyle = image ? getComputedStyle(image) : null;
      const sheetStyle = getComputedStyle(sheet);
      return {
        clientHeight: sheet.clientHeight,
        footer: bounds("footer"),
        header: bounds("header"),
        image: bounds("img"),
        imageStyle: imageStyle
          ? {
              alignSelf: imageStyle.alignSelf,
              justifySelf: imageStyle.justifySelf,
              minHeight: imageStyle.minHeight,
              minWidth: imageStyle.minWidth,
              objectFit: imageStyle.objectFit,
            }
          : null,
        legend: bounds(".civic-dashboard-map-print-sheet__legend"),
        rowGap: Number.parseFloat(sheetStyle.rowGap),
        rect: {
          bottom: rect.bottom,
          height: rect.height,
          left: rect.left,
          right: rect.right,
          top: rect.top,
          width: rect.width,
        },
        scrollHeight: sheet.scrollHeight,
      };
    });

  expect(geometry.header).not.toBeNull();
  expect(geometry.image).not.toBeNull();
  expect(geometry.imageStyle).toEqual({
    alignSelf: "stretch",
    justifySelf: "stretch",
    minHeight: "0px",
    minWidth: "0px",
    objectFit: "contain",
  });
  expect(geometry.legend).not.toBeNull();
  expect(geometry.footer).not.toBeNull();
  expect(geometry.scrollHeight).toBeLessThanOrEqual(geometry.clientHeight + 1);
  expect(geometry.image!.left).toBeCloseTo(geometry.rect.left, 0);
  expect(geometry.image!.right).toBeCloseTo(geometry.rect.right, 0);
  expect(geometry.image!.top).toBeCloseTo(
    geometry.header!.bottom + geometry.rowGap,
    0,
  );
  expect(geometry.image!.bottom).toBeCloseTo(
    geometry.legend!.top - geometry.rowGap,
    0,
  );
  expect(geometry.legend!.bottom + geometry.rowGap).toBeCloseTo(
    geometry.footer!.top,
    0,
  );
  expect(geometry.footer!.bottom).toBeLessThanOrEqual(
    geometry.rect.bottom + 1,
  );
  expect(geometry.rect.height).toBeLessThanOrEqual(9.5 * 96 + 1);
  expect(geometry.rect.bottom).toBeLessThanOrEqual(960);
});

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
