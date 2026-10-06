import { computed, shallowRef } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  rowsToExportFeatures,
  useDownload,
} from "@/pages/composables/useDownload";
import { useBoundariesStore } from "@/shared/stores/boundaries";
import type { LayerConfig } from "@/features/explorer/types";
import { shootingRows } from "../../fixtures/shootings";

function blobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result)));
    reader.addEventListener("error", () => reject(reader.error));
    reader.readAsText(blob);
  });
}

describe("rowsToExportFeatures", () => {
  it("retains every record and represents missing coordinates as null geometry", () => {
    const features = rowsToExportFeatures(shootingRows);

    expect(features).toHaveLength(4);
    expect(features[0].geometry).toEqual({
      type: "Point",
      coordinates: [-75.1602, 39.9526],
    });
    expect(features[2].geometry).toBeNull();
    expect(features[2].properties).not.toHaveProperty("lon");
    expect(features[2].properties).not.toHaveProperty("lat");
  });
});

describe("useDownload", () => {
  let downloadedBlobs: Blob[];

  beforeEach(() => {
    setActivePinia(createPinia());
    downloadedBlobs = [];
    vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
      downloadedBlobs.push(blob as Blob);
      return "blob:test-download";
    });
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  function createDownload() {
    const layers = shallowRef<LayerConfig[]>([
      {
        name: "Neighborhoods",
        source: "boundary-neighborhoods",
        type: "fill",
        aggregated: true,
        column: "neighborhood",
        geoid: "neighborhood",
      },
    ]);
    return useDownload({
      filteredRows: computed(() => shootingRows.filter((row) => row.fatal)),
      allRows: computed(() => shootingRows),
      layers,
    });
  }

  it("uses all rows for an all-data CSV download", async () => {
    const { handleDownload } = createDownload();

    await handleDownload({
      useFiltered: false,
      format: "csv",
      aggregateBy: null,
    });

    const csv = await blobText(downloadedBlobs[0]);
    expect(csv.trim().split("\n")).toHaveLength(5);
    expect(csv).toContain("2026-03");
    expect(csv).toContain("latitude,longitude");
  });

  it("uses only filtered rows for a filtered GeoJSON download", async () => {
    const { handleDownload } = createDownload();

    await handleDownload({
      useFiltered: true,
      format: "geojson",
      aggregateBy: null,
    });

    const geojson = JSON.parse(await blobText(downloadedBlobs[0]));
    expect(geojson.features).toHaveLength(2);
    expect(geojson.features[1].geometry).toBeNull();
    expect(geojson.features[0].properties).not.toHaveProperty("dateInMs");
  });

  it("aggregates filtered records for CSV and joins boundary geometry for GeoJSON", async () => {
    const { handleDownload } = createDownload();
    const boundaries = useBoundariesStore();
    boundaries.dataCache.neighborhoods = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: {
            type: "Polygon",
            coordinates: [],
          },
          properties: { neighborhood: "Center City" },
        },
      ],
    };

    await handleDownload({
      useFiltered: false,
      format: "csv",
      aggregateBy: "Neighborhoods",
    });
    expect(await blobText(downloadedBlobs[0])).toContain(
      "Center City,1,1,0",
    );

    await handleDownload({
      useFiltered: false,
      format: "geojson",
      aggregateBy: "Neighborhoods",
    });
    const geojson = JSON.parse(await blobText(downloadedBlobs[1]));
    expect(geojson.features[0].properties).toMatchObject({
      neighborhood: "Center City",
      total_shootings: 1,
      fatal: 1,
      nonfatal: 0,
    });
  });
});
