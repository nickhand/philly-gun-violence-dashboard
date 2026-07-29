import type { Page, Route } from "@playwright/test";
import {
  rowsNdjson,
  shootingRows,
  shootingsMeta,
} from "../../fixtures/shootings";

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

export async function mockDashboardApi(page: Page): Promise<void> {
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname === "/shootings/meta") {
      return json(route, shootingsMeta);
    }

    if (url.pathname === "/shootings/rows/e2e-fixture-v1/2026.ndjson") {
      return route.fulfill({
        status: 200,
        contentType: "application/x-ndjson",
        body: rowsNdjson,
      });
    }

    if (url.pathname === "/homicides/2026") {
      return json(route, { year: 2026, annual: null, ytd: 10 });
    }

    if (url.pathname === "/meta") {
      const datasetMeta = {
        last_updated: "2026-07-29T12:00:00Z",
        data_through: "2026-07-28",
      };
      return json(route, {
        shootings: datasetMeta,
        homicides: datasetMeta,
        courts: datasetMeta,
      });
    }

    if (url.pathname.startsWith("/boundaries/")) {
      return json(route, { type: "FeatureCollection", features: [] });
    }

    if (url.pathname === "/streets") {
      return json(route, {
        type: "FeatureCollection",
        features: [],
        limit: 2_000,
        offset: 0,
        next_offset: null,
        total: 0,
      });
    }

    if (url.hostname === "nominatim.openstreetmap.org") {
      return json(route, []);
    }

    return route.continue();
  });
}

export { shootingRows };
