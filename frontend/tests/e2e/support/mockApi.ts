import { createRequire } from "node:module";

import type { Page } from "@playwright/test";
import { shootingRows } from "../../fixtures/shootings";

const require = createRequire(import.meta.url);
const mapStyle = require("../../../app/assets/map/style.json") as {
  layers: Array<Record<string, unknown>>;
};

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
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "[]",
    }),
  );
}

export { shootingRows };
