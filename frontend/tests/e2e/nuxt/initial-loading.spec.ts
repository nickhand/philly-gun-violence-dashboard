import { expect, test, type Locator, type Page } from "@playwright/test";

import { mockNuxtExternalServices } from "../support/mockApi";

const allYearsRowsPattern =
  /\/shootings\/rows\/nuxt-e2e-v1\/(?:2025|2026)\.ndjson$/;

function normalizedText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

async function mapFilterGeometry(stage: Locator) {
  const [map, sidebar] = await Promise.all([
    stage.locator(".civic-legacy-map-view").boundingBox(),
    stage.locator(".civic-legacy-sidebar").boundingBox(),
  ]);
  expect(map).not.toBeNull();
  expect(sidebar).not.toBeNull();
  return { map: map!, sidebar: sidebar! };
}

function expectGeometryToRemainStable(
  before: Awaited<ReturnType<typeof mapFilterGeometry>>,
  after: Awaited<ReturnType<typeof mapFilterGeometry>>,
) {
  for (const region of ["map", "sidebar"] as const) {
    for (const dimension of ["x", "y", "width", "height"] as const) {
      expect(
        Math.abs(after[region][dimension] - before[region][dimension]),
        `${region} ${dimension} shifted while detailed records loaded`,
      ).toBeLessThanOrEqual(2);
    }
  }
}

test("keeps the complete shell while the lazy explorer module downloads", async ({
  page,
}) => {
  await page.setViewportSize({ height: 900, width: 1280 });
  await mockNuxtExternalServices(page);

  let markModuleStarted!: () => void;
  let releaseModule!: () => void;
  const moduleStarted = new Promise<void>((resolve) => {
    markModuleStarted = resolve;
  });
  const moduleReleased = new Promise<void>((resolve) => {
    releaseModule = resolve;
  });

  await page.route(
    "**/_nuxt/components/DashboardExplorer.client.vue*",
    async (route) => {
      const response = await route.fetch();
      markModuleStarted();
      await moduleReleased;
      await route.fulfill({ response });
    },
  );

  await page.goto("./?year=All%20Years", { waitUntil: "domcontentloaded" });
  await moduleStarted;
  await page.waitForTimeout(300);

  const explorer = page.locator("#explorer");
  let loadingOutcomeGeometry: Awaited<ReturnType<Locator["boundingBox"]>> =
    null;
  try {
    await expect(
      explorer.locator(".civic-dashboard-map-filter-stage"),
    ).toHaveCount(1);
    await expect(explorer.locator(".civic-legacy-map-view")).toHaveCount(1);
    await expect(explorer.locator(".civic-legacy-sidebar")).toHaveCount(1);
    await expect(explorer.locator("#charts figure")).toHaveCount(5);
    await expect(
      explorer.locator("[data-chart-definition]"),
    ).toHaveCount(0);
    await expect(
      explorer.locator(".civic-dashboard-browser-explorer"),
    ).toHaveCount(0);
    await expect(explorer.getByRole("status")).toHaveCount(1);
    await expect(
      page.locator(".civic-legacy-dashboard-header__summary--shooting"),
    ).toContainText("3 nonfatal and 3 fatal");
    loadingOutcomeGeometry = await explorer
      .locator(".civic-dashboard-category-chart--outcome")
      .boundingBox();
    expect(loadingOutcomeGeometry).not.toBeNull();
  } finally {
    releaseModule();
  }

  await expect(
    explorer.locator(".civic-dashboard-browser-explorer"),
  ).toHaveAttribute("aria-busy", "false");
  await expect(explorer.locator("[data-chart-definition]")).toHaveCount(5);
  const readyOutcomeGeometry = await explorer
    .locator(".civic-dashboard-category-chart--outcome")
    .boundingBox();
  expect(readyOutcomeGeometry).not.toBeNull();
  for (const dimension of ["x", "y", "width", "height"] as const) {
    expect(
      Math.abs(
        readyOutcomeGeometry![dimension] -
          loadingOutcomeGeometry![dimension],
      ),
      `outcome chart ${dimension} shifted when the lazy explorer loaded`,
    ).toBeLessThanOrEqual(2);
  }
});

async function assertStableAllYearsLoading(
  page: Page,
  viewport: { height: number; width: number },
) {
  await page.setViewportSize(viewport);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockNuxtExternalServices(page);

  const requestedFeeds = new Set<string>();
  let markBothFeedsStarted!: () => void;
  let releaseFeeds!: () => void;
  const bothFeedsStarted = new Promise<void>((resolve) => {
    markBothFeedsStarted = resolve;
  });
  const feedsReleased = new Promise<void>((resolve) => {
    releaseFeeds = resolve;
  });

  await page.route(allYearsRowsPattern, async (route) => {
    const response = await route.fetch();
    requestedFeeds.add(new URL(route.request().url()).pathname);
    if (requestedFeeds.size === 2) markBothFeedsStarted();
    await feedsReleased;
    await route.fulfill({ response });
  });

  await page.goto("./?year=All%20Years");
  await bothFeedsStarted;
  await page.evaluate(() => document.fonts.ready);

  const explorer = page.locator(".civic-dashboard-browser-explorer");
  const stage = explorer.locator(".civic-dashboard-map-filter-stage");
  const loadingStage = stage.filter({
    has: page.locator(".civic-dashboard-explorer-loading__feedback"),
  });
  let loadingGeometry:
    | Awaited<ReturnType<typeof mapFilterGeometry>>
    | undefined;

  try {
    expect([...requestedFeeds].sort()).toEqual([
      "/shootings/rows/nuxt-e2e-v1/2025.ndjson",
      "/shootings/rows/nuxt-e2e-v1/2026.ndjson",
    ]);

    await expect(explorer).not.toHaveAttribute("aria-busy", /.+/);
    await expect(loadingStage).toHaveAttribute("aria-busy", "true");
    await expect(explorer.locator('[aria-busy="true"]')).toHaveCount(1);
    await expect(page.locator(".civic-dashboard-point-map")).toHaveCount(0);

    const loadingSidebar = loadingStage.locator("#filters");
    await expect(loadingSidebar).toBeVisible();
    await expect(loadingSidebar).toHaveAttribute("tabindex", "-1");
    await expect(loadingSidebar).toHaveAttribute(
      "aria-label",
      "Map filters loading",
    );
    await expect(
      loadingSidebar.locator(
        ".civic-dashboard-explorer-loading__sidebar-inner",
      ),
    ).toHaveAttribute("inert", "");
    await expect(
      loadingSidebar.locator(
        'a, button, input, select, textarea, [contenteditable="true"], [tabindex]:not([tabindex="-1"])',
      ),
    ).toHaveCount(0);
    await expect(loadingStage.getByRole("status")).toHaveCount(1);
    await expect(loadingStage.getByRole("status")).toContainText(
      "Loading all years record filters and locations",
    );

    const shootingHeadline = page.locator(
      ".civic-legacy-dashboard-header__summary--shooting",
    );
    await expect
      .poll(async () => normalizedText(await shootingHeadline.innerText()))
      .toBe(
        "This map shows the victims of gun violence: 3 nonfatal and 3 fatal shooting victims since 2025.",
      );

    const outcome = page.getByRole("table", {
      name: "Outcome distribution breakdown",
    });
    await expect(
      outcome.getByRole("row", { name: "Fatal 3 50%", exact: true }),
    ).toBeAttached();
    await expect(
      outcome.getByRole("row", { name: "Nonfatal 3 50%", exact: true }),
    ).toBeAttached();

    const court = page.getByRole("table", {
      name: "Court Search Result distribution breakdown",
    });
    await expect(
      court.getByRole("row", { name: "Yes 3 50%", exact: true }),
    ).toBeAttached();
    await expect(
      court.getByRole("row", { name: "No 1 16.7%", exact: true }),
    ).toBeAttached();
    await expect(
      court.getByRole("row", { name: "Unknown 2 33.3%", exact: true }),
    ).toBeAttached();
    await expect(
      explorer.locator("[data-chart-definition]"),
    ).toHaveCount(0);

    const reducedMotionAnimations = await loadingStage.evaluate((element) => {
      const spinner = element.querySelector<HTMLElement>(
        ".civic-dashboard-explorer-loading__spinner",
      )!;
      const sidebar = element.querySelector<HTMLElement>(
        ".civic-dashboard-explorer-loading__sidebar-inner",
      )!;
      return {
        sidebar: getComputedStyle(sidebar).animationName,
        spinner: getComputedStyle(spinner).animationName,
      };
    });
    expect(reducedMotionAnimations).toEqual({
      sidebar: "none",
      spinner: "none",
    });

    loadingGeometry = await mapFilterGeometry(loadingStage);
  } finally {
    releaseFeeds();
  }

  await expect(loadingStage).toHaveCount(0);
  await expect(stage).toHaveAttribute("aria-busy", "false");
  await expect(page.locator("#filters")).toHaveAttribute(
    "aria-label",
    "Map filters and controls",
  );
  await expect(page.locator(".civic-dashboard-point-map")).toHaveClass(
    /civic-dashboard-point-map--ready/,
  );
  await expect(explorer.locator("[data-chart-definition]")).toHaveCount(5);

  const readyGeometry = await mapFilterGeometry(stage);
  expect(loadingGeometry).toBeDefined();
  expectGeometryToRemainStable(loadingGeometry!, readyGeometry);
}

for (const viewport of [
  { height: 900, label: "desktop", width: 1280 },
  { height: 812, label: "mobile", width: 390 },
]) {
  test(`keeps exact All Years summaries and a stable accessible shell at ${viewport.label} width`, async ({
    page,
  }) => {
    await assertStableAllYearsLoading(page, viewport);
  });
}
