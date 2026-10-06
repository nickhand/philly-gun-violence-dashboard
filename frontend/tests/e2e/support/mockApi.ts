import { createRequire } from "node:module";

import type { Page, Route } from "@playwright/test";
import {
  rowsNdjson,
  shootingRows,
  shootingsMeta,
} from "../../fixtures/shootings";

const require = createRequire(import.meta.url);
const mapStyle = require("../../../src/data/style.json") as {
  layers: Array<Record<string, unknown>>;
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

const transparentPixel = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64",
);

const basemapSourceLayers = [
  ...new Set(
    mapStyle.layers.flatMap((layer) =>
      typeof layer["source-layer"] === "string" ? [layer["source-layer"]] : [],
    ),
  ),
];

/**
 * Keep the Nuxt browser contract deterministic while still constructing a real
 * MapLibre map. Only third-party basemap and geocoder traffic is intercepted;
 * dashboard data comes from the cross-origin HTTP fixture server.
 */
export async function mockNuxtExternalServices(page: Page): Promise<void> {
  await page.route("https://basemaps-api.arcgis.com/**", async (route) => {
    const url = new URL(route.request().url());
    if (
      url.pathname.includes("/resources/fonts/") ||
      url.pathname.includes("/tile/")
    ) {
      return route.fulfill({
        status: 200,
        contentType: "application/x-protobuf",
        headers: { "access-control-allow-origin": "*" },
        body: Buffer.alloc(0),
      });
    }

    return route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify({
        tilejson: "2.2.0",
        attribution: "© OpenStreetMap contributors",
        minzoom: 0,
        maxzoom: 16,
        tiles: ["http://127.0.0.1:4181/tiles/{z}/{x}/{y}.pbf"],
        vector_layers: basemapSourceLayers.map((id) => ({
          id,
          fields: {},
          minzoom: 0,
          maxzoom: 16,
        })),
      }),
    });
  });

  await page.route("https://cdn.arcgis.com/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith(".png")) {
      return route.fulfill({
        status: 200,
        contentType: "image/png",
        headers: { "access-control-allow-origin": "*" },
        body: transparentPixel,
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: "{}",
    });
  });

  await page.route("https://nominatim.openstreetmap.org/**", (route) =>
    json(route, []),
  );
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
