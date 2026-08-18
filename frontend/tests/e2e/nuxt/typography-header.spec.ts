import { expect, test, type Page } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";

type FontContract = {
  family: string;
  status: FontFace["status"];
  style: string;
  weight: string;
};

async function waitForPublicSans(page: Page): Promise<FontContract[]> {
  return page.evaluate(async () => {
    await document.fonts.ready;

    const faces: FontContract[] = [];
    document.fonts.forEach((face) => {
      if (face.family.replace(/["']/g, "").trim() !== "Public Sans Web") return;
      faces.push({
        family: face.family.replace(/["']/g, "").trim(),
        status: face.status,
        style: face.style,
        weight: face.weight,
      });
    });
    return faces;
  });
}

test.use({ viewport: { height: 900, width: 1440 } });

test("loads true semibold and keeps the intended type hierarchy", async ({
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

  const fontFaces = await waitForPublicSans(page);
  expect(fontFaces).toContainEqual({
    family: "Public Sans Web",
    status: "loaded",
    style: "normal",
    weight: "600",
  });

  const shellWeights = await page.evaluate(() => {
    const weightFor = (selector: string) => {
      const element = document.querySelector<HTMLElement>(selector);
      return element ? getComputedStyle(element).fontWeight : null;
    };

    return {
      brand: weightFor(".civic-site-header__brand"),
      currentNavigation: weightFor(
        ".civic-site-header__nav a[aria-current='page']",
      ),
      inactiveNavigation: Array.from(
        document.querySelectorAll<HTMLElement>(
          ".civic-site-header__nav a:not([aria-current='page'])",
        ),
        (link) => getComputedStyle(link).fontWeight,
      ),
      statsTotals: Array.from(
        document.querySelectorAll<HTMLElement>(".civic-stat-total"),
        (total) => getComputedStyle(total).fontWeight,
      ),
    };
  });

  expect(shellWeights.brand).toBe("600");
  expect(shellWeights.currentNavigation).toBe("600");
  expect(shellWeights.inactiveNavigation.length).toBeGreaterThan(0);
  expect(new Set(shellWeights.inactiveNavigation)).toEqual(new Set(["400"]));
  expect(shellWeights.statsTotals.length).toBe(2);
  expect(new Set(shellWeights.statsTotals)).toEqual(new Set(["600"]));

  const referencePages = ["./about", "./data", "./methodology", "./stats"];
  const headingLevels = new Set<string>();
  let tableRowHeaderCount = 0;

  for (const path of referencePages) {
    await test.step(`type hierarchy on ${path}`, async () => {
      await page.goto(path);
      await expect(page.locator("main.civic-reference-page h1")).toBeVisible();
      await waitForPublicSans(page);

      const typography = await page.evaluate(() => ({
        headings: Array.from(
          document.querySelectorAll<HTMLElement>(
            "main.civic-reference-page h1, main.civic-reference-page h2, main.civic-reference-page h3",
          ),
          (heading) => ({
            tag: heading.tagName,
            weight: getComputedStyle(heading).fontWeight,
          }),
        ),
        rowHeaders: Array.from(
          document.querySelectorAll<HTMLElement>(
            "main.civic-reference-page tbody th[scope='row']",
          ),
          (heading) => getComputedStyle(heading).fontWeight,
        ),
      }));

      expect(typography.headings.length).toBeGreaterThan(0);
      for (const heading of typography.headings) {
        headingLevels.add(heading.tag);
        expect(heading.weight).toBe("600");
      }

      tableRowHeaderCount += typography.rowHeaders.length;
      for (const weight of typography.rowHeaders) {
        expect(weight).toBe("400");
      }
    });
  }

  expect(headingLevels).toEqual(new Set(["H1", "H2", "H3"]));
  expect(tableRowHeaderCount).toBeGreaterThan(0);

  await page.goto("./");
  await expect(
    page.locator(".civic-legacy-dashboard-header__summary--shooting"),
  ).toContainText("This map shows the victims of gun violence:");
  await waitForPublicSans(page);

  const homepageWeights = await page.evaluate(() => ({
    accent: Array.from(
      document.querySelectorAll<HTMLElement>(
        ".civic-legacy-dashboard-header__summary .fatal, .civic-legacy-dashboard-header__summary .nonfatal",
      ),
      (element) => getComputedStyle(element).fontWeight,
    ),
    narrative: Array.from(
      document.querySelectorAll<HTMLElement>(
        ".civic-legacy-dashboard-header__summary",
      ),
      (element) => getComputedStyle(element).fontWeight,
    ),
    title: getComputedStyle(
      document.querySelector<HTMLElement>(
        ".civic-legacy-dashboard-header h1",
      )!,
    ).fontWeight,
  }));

  expect(homepageWeights.narrative.length).toBe(2);
  expect(new Set(homepageWeights.narrative)).toEqual(new Set(["300"]));
  expect(homepageWeights.accent.length).toBeGreaterThanOrEqual(2);
  expect(new Set(homepageWeights.accent)).toEqual(new Set(["300"]));
  expect(homepageWeights.title).toBe("300");
});

test("the site header uses the viewport with deliberate responsive gutters", async ({
  page,
}) => {
  await mockNuxtExternalServices(page);
  await page.goto("./");
  await expect(page.locator(".civic-site-header__brand")).toBeVisible();

  const desktop = await page.evaluate(() => {
    const inner = document.querySelector<HTMLElement>(
      ".civic-site-header__inner",
    )!;
    const brand = document.querySelector<HTMLElement>(
      ".civic-site-header__brand",
    )!;
    const navigation = document.querySelector<HTMLElement>(
      ".civic-site-header__navigation",
    )!;
    const yearForm = document.querySelector<HTMLFormElement>(
      ".civic-legacy-year-bar form",
    )!;
    const innerBounds = inner.getBoundingClientRect();
    const brandBounds = brand.getBoundingClientRect();
    const navigationBounds = navigation.getBoundingClientRect();
    const yearFormBounds = yearForm.getBoundingClientRect();
    const style = getComputedStyle(inner);

    return {
      brandGutter: brandBounds.left,
      innerLeft: innerBounds.left,
      innerRight: innerBounds.right,
      maxWidth: style.maxWidth,
      navigationGutter: window.innerWidth - navigationBounds.right,
      paddingLeft: Number.parseFloat(style.paddingLeft),
      paddingRight: Number.parseFloat(style.paddingRight),
      viewportWidth: window.innerWidth,
      yearControlGutter: window.innerWidth - yearFormBounds.right,
    };
  });

  expect(desktop.maxWidth).toBe("none");
  expect(desktop.innerLeft).toBeCloseTo(0, 0);
  expect(desktop.innerRight).toBeCloseTo(desktop.viewportWidth, 0);
  expect(desktop.paddingLeft).toBeGreaterThanOrEqual(32);
  expect(desktop.paddingLeft).toBeLessThanOrEqual(48);
  expect(desktop.paddingRight).toBeGreaterThanOrEqual(32);
  expect(desktop.paddingRight).toBeLessThanOrEqual(48);
  expect(desktop.brandGutter).toBeCloseTo(desktop.paddingLeft, 0);
  expect(desktop.navigationGutter).toBeCloseTo(desktop.paddingRight, 0);
  expect(desktop.yearControlGutter).toBeCloseTo(
    desktop.navigationGutter,
    0,
  );

  await page.setViewportSize({ height: 812, width: 375 });
  await expect(page.getByRole("button", { name: "Menu" })).toBeVisible();

  const mobile = await page.evaluate(() => {
    const inner = document.querySelector<HTMLElement>(
      ".civic-site-header__inner",
    )!;
    const brand = document.querySelector<HTMLElement>(
      ".civic-site-header__brand",
    )!;
    const menu = document.querySelector<HTMLElement>(
      ".civic-site-header__menu-button",
    )!;
    const yearBar = document.querySelector<HTMLElement>(
      ".civic-legacy-year-bar",
    )!;
    const yearForm = yearBar.querySelector<HTMLFormElement>("form")!;
    const innerBounds = inner.getBoundingClientRect();
    const brandBounds = brand.getBoundingClientRect();
    const menuBounds = menu.getBoundingClientRect();
    const yearBarBounds = yearBar.getBoundingClientRect();
    const yearFormBounds = yearForm.getBoundingClientRect();
    const style = getComputedStyle(inner);

    return {
      brandGutter: brandBounds.left,
      innerLeft: innerBounds.left,
      innerRight: innerBounds.right,
      maxWidth: style.maxWidth,
      menuGutter: window.innerWidth - menuBounds.right,
      paddingLeft: Number.parseFloat(style.paddingLeft),
      paddingRight: Number.parseFloat(style.paddingRight),
      rootScrollWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
      yearBarLeft: yearBarBounds.left,
      yearBarRight: yearBarBounds.right,
      yearControlGutter: window.innerWidth - yearFormBounds.right,
      yearFormLeft: yearFormBounds.left,
      yearFormRight: yearFormBounds.right,
    };
  });

  expect(mobile.maxWidth).toBe("none");
  expect(mobile.innerLeft).toBeCloseTo(0, 0);
  expect(mobile.innerRight).toBeCloseTo(mobile.viewportWidth, 0);
  expect(mobile.paddingLeft).toBeCloseTo(16, 0);
  expect(mobile.paddingRight).toBeCloseTo(16, 0);
  expect(mobile.brandGutter).toBeCloseTo(mobile.paddingLeft, 0);
  expect(mobile.menuGutter).toBeCloseTo(mobile.paddingRight, 0);
  expect(mobile.yearControlGutter).toBeCloseTo(mobile.menuGutter, 0);
  expect(mobile.yearBarLeft).toBeGreaterThanOrEqual(0);
  expect(mobile.yearBarRight).toBeLessThanOrEqual(mobile.viewportWidth);
  expect(mobile.yearFormLeft).toBeGreaterThanOrEqual(mobile.yearBarLeft);
  expect(mobile.yearFormRight).toBeLessThanOrEqual(mobile.yearBarRight);
  expect(mobile.rootScrollWidth).toBeLessThanOrEqual(mobile.viewportWidth);
});
