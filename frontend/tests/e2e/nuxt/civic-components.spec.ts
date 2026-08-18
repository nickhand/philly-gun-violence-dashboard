import { expect, test } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";

// Keep this title free of "print": the WebKit project excludes PDF-only tests
// by title, while this atomic-page regression must run there.
test("keeps one atomic portrait map image inside its bounded sheet", async ({
  page,
}) => {
  await page.setViewportSize({ height: 844, width: 390 });
  await mockNuxtExternalServices(page);
  await page.goto("./about");
  await page.evaluate(async () => {
    const pageImage = [
      '<svg xmlns="http://www.w3.org/2000/svg" width="1450" height="1800" viewBox="0 0 1450 1800">',
      '<rect width="1450" height="1800" fill="#fff"/>',
      '<rect x="60" y="200" width="1330" height="1420" fill="#202a2f"/>',
      "</svg>",
    ].join("");

    const sheet = document.createElement("section");
    sheet.className = "civic-dashboard-map-print-sheet";
    sheet.setAttribute("aria-label", "Printable map fixture");
    const image = document.createElement("img");
    image.alt = "Portrait map fixture";
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(pageImage)}`;
    sheet.append(image);
    document.documentElement.classList.add(
      "civic-dashboard-map-print-active",
    );
    document.body.classList.add("civic-dashboard-map-print-active");
    document.body.append(sheet);

    await image.decode();
    await document.fonts.ready;
  });
  await page.emulateMedia({ media: "print" });

  const geometry = await page
    .locator(".civic-dashboard-map-print-sheet")
    .evaluate((sheet) => {
      const rect = sheet.getBoundingClientRect();
      const image = sheet.querySelector<HTMLImageElement>("img");
      if (!image) throw new Error("Map fixture image was not created");
      const imageRect = image.getBoundingClientRect();
      const imageStyle = image ? getComputedStyle(image) : null;
      const sheetStyle = getComputedStyle(sheet);
      return {
        clientHeight: sheet.clientHeight,
        clientWidth: sheet.clientWidth,
        directChildren: Array.from(sheet.children, (child) => child.tagName),
        image: {
          bottom: imageRect.bottom,
          height: imageRect.height,
          left: imageRect.left,
          naturalHeight: image.naturalHeight,
          naturalWidth: image.naturalWidth,
          right: imageRect.right,
          top: imageRect.top,
          width: imageRect.width,
        },
        imageStyle: imageStyle
          ? {
              display: imageStyle.display,
              height: imageStyle.height,
              objectFit: imageStyle.objectFit,
              width: imageStyle.width,
            }
          : null,
        rect: {
          bottom: rect.bottom,
          height: rect.height,
          left: rect.left,
          right: rect.right,
          top: rect.top,
          width: rect.width,
        },
        scrollHeight: sheet.scrollHeight,
        scrollWidth: sheet.scrollWidth,
        sheetStyle: {
          display: sheetStyle.display,
          height: sheetStyle.height,
          overflow: sheetStyle.overflow,
          width: sheetStyle.width,
        },
      };
    });

  expect(geometry.directChildren).toEqual(["IMG"]);
  expect(geometry.image.naturalWidth).toBe(1450);
  expect(geometry.image.naturalHeight).toBe(1800);
  expect(geometry.sheetStyle).toEqual({
    display: "block",
    height: "864px",
    overflow: "hidden",
    width: "696px",
  });
  expect(geometry.imageStyle).toEqual({
    display: "block",
    height: "864px",
    objectFit: "contain",
    width: "696px",
  });
  expect(geometry.scrollHeight).toBeLessThanOrEqual(geometry.clientHeight + 1);
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth + 1);
  expect(geometry.image!.left).toBeCloseTo(geometry.rect.left, 0);
  expect(geometry.image!.right).toBeCloseTo(geometry.rect.right, 0);
  expect(geometry.image!.top).toBeCloseTo(geometry.rect.top, 0);
  expect(geometry.image!.bottom).toBeCloseTo(geometry.rect.bottom, 0);
  expect(geometry.rect.width).toBeCloseTo(7.25 * 96, 0);
  expect(geometry.rect.height).toBeCloseTo(9 * 96, 0);
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
