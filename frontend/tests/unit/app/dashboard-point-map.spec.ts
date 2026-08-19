import { mount } from "@vue/test-utils";
import type { FeatureCollection, Geometry } from "geojson";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import DashboardPointMap from "../../../app/components/DashboardPointMap.client.vue";
import {
  DEFAULT_MAP_LAYERS,
  formatMapLayersParam,
  parseMapLayersParam,
  type MapLayerId,
} from "../../../app/utils/mapLayers";
import {
  DEFAULT_MAP_VIEW,
  formatMapViewParam,
  parseMapViewParam,
} from "../../../app/utils/mapView";
import {
  boundaryOverlayConfig,
  joinBoundaryCounts,
  joinStreetCounts,
} from "../../../app/utils/mapOverlays";
import {
  createShootingFilterState,
  filterShootingRows,
  hasActiveShootingFilters,
  shootingHistogram,
} from "../../../app/utils/shootingFilters";
import {
  loadShootingRecords,
  parseShootingRows,
  rowsToShootingPoints,
  summarizeShootingRecords,
  type ShootingRow,
} from "../../../app/utils/shootingRecords";
import {
  rowsNdjson,
  shootingRows,
} from "../../fixtures/shootings";

const maplibre = vi.hoisted(() => {
  const instances: Array<Record<string, any>> = [];

  const Map = vi.fn(function Map(options: Record<string, unknown>) {
    let loadListener: (() => void) | undefined;
    const eventListeners = new globalThis.Map<
      string,
      Set<(event?: unknown) => void>
    >();
    const layerListeners = new globalThis.Map<
      string,
      Set<(event?: unknown) => void>
    >();
    const sources = new globalThis.Map<string, Record<string, any>>();
    const layers = new globalThis.Map<string, Record<string, any>>();
    const controls = new Set<Record<string, any>>();
    let center = options.center as [number, number];
    let zoom = options.zoom as number;
    const canvas = document.createElement("canvas");
    canvas.setAttribute("aria-label", "Map");
    const instance: Record<string, any> = {
      options,
      activeControls: () => [...controls],
      addControl: vi.fn((control: Record<string, any>) => {
        controls.add(control);
      }),
      addLayer: vi.fn((layer: Record<string, any>) => {
        layers.set(layer.id, layer);
      }),
      addSource: vi.fn((id: string, source: Record<string, unknown>) => {
        sources.set(id, { ...source, setData: vi.fn() });
      }),
      getCanvas: vi.fn(() => canvas),
      getCenter: vi.fn(() => ({ lat: center[1], lng: center[0] })),
      getLayer: vi.fn((id: string) => layers.get(id)),
      getLayoutProperty: vi.fn(
        (id: string, property: string) => layers.get(id)?.layout?.[property],
      ),
      getSource: vi.fn((id: string) => sources.get(id)),
      getZoom: vi.fn(() => zoom),
      flyTo: vi.fn((view: { center: [number, number]; zoom: number }) => {
        center = view.center;
        zoom = view.zoom;
      }),
      jumpTo: vi.fn(
        (view: { center: [number, number]; zoom: number }) => {
          center = view.center;
          zoom = view.zoom;
        },
      ),
      off: vi.fn(
        (
          event: string,
          layerOrListener: string | (() => void),
          listener?: (event?: unknown) => void,
        ) => {
          if (typeof layerOrListener === "function") {
            const listeners = eventListeners.get(event);
            listeners?.delete(layerOrListener);
            if (listeners?.size === 0) eventListeners.delete(event);
          } else if (typeof layerOrListener === "string" && listener) {
            const key = `${event}:${layerOrListener}`;
            const listeners = layerListeners.get(key);
            listeners?.delete(listener);
            if (listeners?.size === 0) layerListeners.delete(key);
          }
        }
      ),
      on: vi.fn(
        (
          event: string,
          layerOrListener: string | (() => void),
          listener?: (event?: unknown) => void,
        ) => {
          if (typeof layerOrListener === "function") {
            const listeners = eventListeners.get(event) ?? new Set();
            listeners.add(layerOrListener);
            eventListeners.set(event, listeners);
          } else if (typeof layerOrListener === "string" && listener) {
            const key = `${event}:${layerOrListener}`;
            const listeners = layerListeners.get(key) ?? new Set();
            listeners.add(listener);
            layerListeners.set(key, listeners);
          }
        },
      ),
      once: vi.fn((event: string, listener: () => void) => {
        if (event === "load") loadListener = listener;
      }),
      remove: vi.fn(() => controls.clear()),
      removeControl: vi.fn((control: Record<string, any>) => {
        controls.delete(control);
      }),
      removeLayer: vi.fn((id: string) => layers.delete(id)),
      removeSource: vi.fn((id: string) => sources.delete(id)),
      setLayoutProperty: vi.fn((id: string, property: string, value: unknown) => {
        const layer = layers.get(id);
        if (layer) {
          layer.layout = { ...layer.layout, [property]: value };
        }
      }),
      setPaintProperty: vi.fn(),
      setView: (nextCenter: [number, number], nextZoom: number) => {
        center = nextCenter;
        zoom = nextZoom;
      },
      activeLayerListenerCount: (event: string, layer: string) =>
        layerListeners.get(`${event}:${layer}`)?.size ?? 0,
      activeEventListenerCount: (event: string) =>
        eventListeners.get(event)?.size ?? 0,
      triggerEvent: (event: string, payload?: unknown) => {
        for (const listener of eventListeners.get(event) ?? []) listener(payload);
      },
      triggerLoad: () => loadListener?.(),
      triggerLayerEvent: (event: string, layer: string, payload?: unknown) => {
        for (const listener of layerListeners.get(`${event}:${layer}`) ?? []) {
          listener(payload);
        }
      },
      triggerMoveEnd: () => {
        for (const listener of eventListeners.get("moveend") ?? []) listener();
      },
    };
    instances.push(instance);
    return instance;
  });

  const NavigationControl = vi.fn(function NavigationControl(
    options: Record<string, unknown>,
  ) {
    return { kind: "navigation", options };
  });
  const ScaleControl = vi.fn(function ScaleControl() {
    return { kind: "scale" };
  });
  const AttributionControl = vi.fn(function AttributionControl(
    options: Record<string, unknown>,
  ) {
    return { kind: "attribution", options };
  });

  const popups: Array<Record<string, any>> = [];
  const Popup = vi.fn(function Popup(options: Record<string, unknown>) {
    const instance: Record<string, any> = {
      options,
      addTo: vi.fn(),
      on: vi.fn(),
      remove: vi.fn(),
      setDOMContent: vi.fn(),
      setLngLat: vi.fn(),
    };
    instance.addTo.mockImplementation(() => instance);
    instance.on.mockImplementation(() => instance);
    instance.setDOMContent.mockImplementation(() => instance);
    instance.setLngLat.mockImplementation(() => instance);
    popups.push(instance);
    return instance;
  });

  return {
    AttributionControl,
    instances,
    Map,
    NavigationControl,
    Popup,
    popups,
    ScaleControl,
  };
});

let routeQuery: Record<string, string | string[]>;
const routerReplace = vi.fn();
const mockedRoute = {
  get query() {
    return routeQuery;
  },
};

vi.mock("maplibre-gl", () => ({
  default: {
    AttributionControl: maplibre.AttributionControl,
    Map: maplibre.Map,
    NavigationControl: maplibre.NavigationControl,
    Popup: maplibre.Popup,
    ScaleControl: maplibre.ScaleControl,
  },
}));

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function textResponse(value: string, status = 200): Response {
  return new Response(value, {
    status,
    headers: { "Content-Type": "application/x-ndjson" },
  });
}

function metaWithRowsUrl(rowsUrl: string, rows = shootingRows.length) {
  return {
    years_meta: {
      2026: { rows, rows_url: rowsUrl },
    },
  };
}

function recordResult(rows: ShootingRow[] = shootingRows) {
  return summarizeShootingRecords(rows);
}

type AggregateLegendId = "choropleth" | "street-hot-spots";

function legendContract(root: ParentNode, id: AggregateLegendId) {
  const legend = root.querySelector<HTMLElement>(`[data-map-legend="${id}"]`);
  if (!legend) return null;

  const normalizedText = (selector: string) =>
    legend
      .querySelector(selector)
      ?.textContent?.replace(/\s+/g, " ")
      .trim();

  return {
    accessibleName: legend.getAttribute("aria-label"),
    barStyle: legend
      .querySelector<HTMLElement>("[data-map-legend-bar]")
      ?.getAttribute("style"),
    key: normalizedText(".civic-dashboard-map-legend__key"),
    scale: legend.dataset.mapLegendScale,
    ticks: Array.from(
      legend.querySelectorAll<HTMLElement>("[data-map-legend-tick]"),
      (tick) => ({
        label: tick.textContent?.trim(),
        left: tick.style.left,
        value: tick.dataset.value,
      }),
    ),
    title: normalizedText(".civic-dashboard-map-legend__label span"),
    zero: legend.querySelector('[data-map-legend-min="empty"]')?.textContent,
    zeroColor: legend
      .querySelector<HTMLElement>("[data-map-legend-zero] span")
      ?.getAttribute("style"),
  };
}

function composedPrintSvg(root: HTMLElement): SVGSVGElement {
  expect(Array.from(root.children, (child) => child.tagName)).toEqual(["IMG"]);
  const source = root.firstElementChild?.getAttribute("src");
  expect(source).toMatch(/^data:image\/svg\+xml;charset=utf-8,/);
  const svgSource = decodeURIComponent(source!.slice(source!.indexOf(",") + 1));
  const document = new DOMParser().parseFromString(svgSource, "image/svg+xml");
  expect(document.querySelector("parsererror")).toBeNull();
  return document.documentElement as unknown as SVGSVGElement;
}

function deferredResponse() {
  let resolve!: (response: Response) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<Response>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, reject, resolve };
}

async function settleInitialMap(instance: Record<string, any>): Promise<void> {
  await vi.waitFor(() =>
    expect(instance.getLayer("city-limits-line")).toBeDefined(),
  );
  instance.triggerEvent("idle");
  await nextTick();
}

describe("map layer helpers", () => {
  it.each([
    [undefined, ["point-locations"]],
    ["", []],
    ["point-locations", ["point-locations"]],
    ["heat-map", ["heat-map"]],
    ["point-locations,heat-map", ["point-locations", "heat-map"]],
    ["heat-map,point-locations", ["point-locations", "heat-map"]],
    [
      "heat-map,hot-spots-by-street-block",
      ["heat-map", "hot-spots-by-street-block"],
    ],
    ["police-districts", ["police-districts"]],
  ])("parses %j into the supported map layers", (value, expected) => {
    expect(parseMapLayersParam(value)).toEqual(expected);
  });

  it.each([
    ["unknown", ["point-locations"]],
    ["point-locations,point-locations", ["point-locations"]],
    ["police-districts,heat-map", ["point-locations"]],
    ["police-districts,hot-spots-by-street-block", ["point-locations"]],
    ["police-districts,zip-codes", ["point-locations"]],
    [["point-locations", "heat-map"], ["point-locations"]],
  ])("falls back for invalid layer value %j", (value, expected) => {
    expect(parseMapLayersParam(value)).toEqual(expected);
  });

  it("formats layers in one stable order", () => {
    expect(formatMapLayersParam(["heat-map", "point-locations"])).toBe(
      "point-locations,heat-map",
    );
  });
});

describe("aggregate map counts", () => {
  it("counts only records matched to a rendered geography or street block", () => {
    const boundary = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [-75.16, 39.95] },
          properties: { police_district: "6" },
        },
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [-75.17, 39.96] },
          properties: { police_district: "6" },
        },
      ],
    } as FeatureCollection<Geometry>;
    const streets = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "LineString", coordinates: [] },
          properties: { segment_id: "segment-1" },
        },
      ],
    } as FeatureCollection<Geometry>;
    const rows = shootingRows.slice(0, 3);

    const boundaryCounts = joinBoundaryCounts(
      boundary,
      rows,
      boundaryOverlayConfig("police-districts"),
    );
    const streetCounts = joinStreetCounts(streets, rows);

    expect(boundaryCounts.representedCount).toBe(1);
    expect(streetCounts.representedCount).toBe(1);
    expect(boundaryCounts.features).toHaveLength(2);
    expect(boundaryCounts.features[0]?.properties.total_shootings).toBe(1);
    expect(boundaryCounts.features[1]?.properties.total_shootings).toBe(1);
  });
});

describe("map view helpers", () => {
  it("parses and formats the public zoom/latitude/longitude grammar", () => {
    expect(parseMapViewParam("12.76/39.97240/-75.14142")).toEqual({
      center: [-75.14142, 39.9724],
      zoom: 12.76,
    });
    expect(
      formatMapViewParam({ center: [-75.141423, 39.972404], zoom: 12.764 }),
    ).toBe("12.76/39.97240/-75.14142");
  });

  it.each([
    undefined,
    ["12/40/-75"],
    "12/40",
    "12//-75",
    "12x/40/-75",
    "8.99/40/-75",
    "18.01/40/-75",
    "12/91/-75",
    "12/40/-181",
  ])("rejects invalid map view value %#", (value) => {
    expect(parseMapViewParam(value)).toBeNull();
  });
});

describe("shooting record helpers", () => {
  it("parses NDJSON and maps only finite in-range coordinates", () => {
    const parsed = parseShootingRows(
      `${rowsNdjson.replace(/\n/g, "\r\n")}\r\n\r\n`,
    );
    const points = rowsToShootingPoints([
      ...parsed,
      {
        fatal: true,
        has_court_case: null,
        lat: Number.POSITIVE_INFINITY,
        lon: -75,
      },
      { fatal: false, has_court_case: null, lat: 91, lon: -75 },
      { fatal: false, has_court_case: null, lat: 40, lon: -181 },
    ] satisfies ShootingRow[]);

    expect(parsed).toHaveLength(4);
    expect(points.features).toHaveLength(3);
    expect(points.features.map((feature) => feature.geometry.coordinates)).toEqual([
      [-75.1602, 39.9526],
      [-75.1652, 39.9496],
      [-75.158, 40.012],
    ]);
    expect(points.features.map((feature) => feature.properties)).toEqual([
      {
        age: 24,
        date: "2026-01-05",
        dcKey: "2026-01",
        fatal: true,
        hasCourtCase: true,
        race: "B",
        sex: "M",
        streetBlock: "1200 block of MARKET ST",
        timeInMs: 3_600_000,
      },
      {
        age: 36,
        date: "2026-02-10",
        dcKey: "2026-02",
        fatal: false,
        hasCourtCase: null,
        race: "W",
        sex: "F",
        streetBlock: "500 block of BROAD ST",
        timeInMs: 43_200_000,
      },
      {
        age: null,
        date: "2026-04-20",
        dcKey: "2026-04",
        fatal: false,
        hasCourtCase: false,
        race: "B",
        sex: "M",
        streetBlock: "4300 block of GERMANTOWN AVE",
        timeInMs: 82_800_000,
      },
    ]);
  });

  it("omits invalid date and incomplete nearest-street context from points", () => {
    const points = rowsToShootingPoints([
      {
        block_number: "1200",
        date: "2026-02-30",
        fatal: false,
        has_court_case: null,
        lat: 39.95,
        lon: -75.16,
        street_name: "MARKET ST",
      },
    ]);

    expect(points.features[0]?.properties).toEqual({
      age: null,
      date: null,
      dcKey: null,
      fatal: false,
      hasCourtCase: null,
      race: null,
      sex: null,
      streetBlock: null,
      timeInMs: null,
    });
  });

  it("rejects malformed JSON and invalid row shapes with line context", () => {
    const valid = JSON.stringify({
      fatal: true,
      has_court_case: null,
      lat: 40,
      lon: -75,
    });

    expect(() => parseShootingRows(`${valid}\nnot-json`)).toThrow(
      "Invalid shooting record on line 2.",
    );
    expect(() =>
      parseShootingRows(
        '{"fatal":true,"has_court_case":null,"lat":"40","lon":-75}',
      ),
    ).toThrow("Invalid shooting record on line 1.");
  });

  it("accepts only boolean or null court-search values", () => {
    expect(
      parseShootingRows(
        '{"fatal":true,"has_court_case":null,"lat":40,"lon":-75}',
      )[0]?.has_court_case,
    ).toBeNull();

    for (const record of [
      { fatal: true, lat: 40, lon: -75 },
      { fatal: true, has_court_case: "false", lat: 40, lon: -75 },
      { fatal: true, has_court_case: 0, lat: 40, lon: -75 },
    ]) {
      expect(() => parseShootingRows(JSON.stringify(record))).toThrow(
        "Invalid shooting record on line 1.",
      );
    }
  });

  it("loads the selected year from the manifest-provided URL", async () => {
    const signal = new AbortController().signal;
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(metaWithRowsUrl("/opaque/content-addressed-feed.ndjson")),
      )
      .mockResolvedValueOnce(textResponse(rowsNdjson));

    const result = await loadShootingRecords("https://api.example.test/base/", 2026, {
      fetcher,
      signal,
    });

    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "https://api.example.test/base/shootings/meta",
      { headers: { Accept: "application/json" }, signal },
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      "https://api.example.test/base/opaque/content-addressed-feed.ndjson",
      { headers: { Accept: "application/x-ndjson" }, signal },
    );
    expect(result.recordCount).toBe(4);
    expect(result.fatalRecordCount).toBe(2);
    expect(result.nonfatalRecordCount).toBe(2);
    expect(result.points.features).toHaveLength(3);
    expect(result.rows).toEqual(shootingRows);
  });

  it("loads every manifest year atomically and ignores the aggregate metadata total", async () => {
    const firstRows = shootingRows.slice(0, 2);
    const secondRows = shootingRows.slice(2);
    const meta = {
      rows: 999,
      years_meta: {
        2025: { rows: 2, rows_url: "/opaque/2025.ndjson" },
        2026: { rows: 2, rows_url: "/opaque/2026.ndjson" },
      },
    };
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(meta))
      .mockResolvedValueOnce(
        textResponse(firstRows.map((row) => JSON.stringify(row)).join("\n")),
      )
      .mockResolvedValueOnce(
        textResponse(secondRows.map((row) => JSON.stringify(row)).join("\n")),
      );

    const result = await loadShootingRecords(
      "https://api.example.test/base/",
      null,
      { fetcher },
    );

    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "https://api.example.test/base/shootings/meta",
      "https://api.example.test/base/opaque/2026.ndjson",
      "https://api.example.test/base/opaque/2025.ndjson",
    ]);
    expect(result.recordCount).toBe(4);
    expect(result.rows).toEqual([...firstRows, ...secondRows]);
  });

  it("does not return a partial All Years result when one feed fails", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          years_meta: {
            2025: { rows: 2, rows_url: "/opaque/2025.ndjson" },
            2026: { rows: 2, rows_url: "/opaque/2026.ndjson" },
          },
        }),
      )
      .mockResolvedValueOnce(textResponse(rowsNdjson, 503))
      .mockResolvedValueOnce(textResponse(rowsNdjson));

    await expect(
      loadShootingRecords("https://api.example.test", null, { fetcher }),
    ).rejects.toThrow("Shooting data request failed with 503.");
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("retries the complete All Years selection after any stale row URL", async () => {
    const firstRows = shootingRows.slice(0, 2);
    const secondRows = shootingRows.slice(2);
    const meta = (version: number) => ({
      years_meta: {
        2025: { rows: 2, rows_url: `/rows/v${version}/2025.ndjson` },
        2026: { rows: 2, rows_url: `/rows/v${version}/2026.ndjson` },
      },
    });
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(meta(1)))
      .mockResolvedValueOnce(textResponse(rowsNdjson, 404))
      .mockResolvedValueOnce(textResponse(rowsNdjson))
      .mockResolvedValueOnce(jsonResponse(meta(2)))
      .mockResolvedValueOnce(
        textResponse(firstRows.map((row) => JSON.stringify(row)).join("\n")),
      )
      .mockResolvedValueOnce(
        textResponse(secondRows.map((row) => JSON.stringify(row)).join("\n")),
      );

    await expect(
      loadShootingRecords("https://api.example.test", null, { fetcher }),
    ).resolves.toMatchObject({ recordCount: 4 });
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "https://api.example.test/shootings/meta",
      "https://api.example.test/rows/v1/2026.ndjson",
      "https://api.example.test/rows/v1/2025.ndjson",
      "https://api.example.test/shootings/meta",
      "https://api.example.test/rows/v2/2026.ndjson",
      "https://api.example.test/rows/v2/2025.ndjson",
    ]);
  });

  it("rejects failed, unavailable, malformed, and incomplete record responses", async () => {
    await expect(
      loadShootingRecords("https://api.example.test", 2026, {
        fetcher: vi.fn().mockResolvedValue(textResponse("", 503)),
      }),
    ).rejects.toThrow("Shooting data request failed with 503.");

    await expect(
      loadShootingRecords("https://api.example.test", 2026, {
        fetcher: vi.fn().mockResolvedValue(jsonResponse({ years_meta: {} })),
      }),
    ).rejects.toThrow("Shooting records are not available for 2026.");

    await expect(
      loadShootingRecords("https://api.example.test", 2026, {
        fetcher: vi
          .fn()
          .mockResolvedValueOnce(jsonResponse(metaWithRowsUrl("/rows.ndjson")))
          .mockResolvedValueOnce(textResponse("", 500)),
      }),
    ).rejects.toThrow("Shooting data request failed with 500.");

    await expect(
      loadShootingRecords("https://api.example.test", 2026, {
        fetcher: vi
          .fn()
          .mockResolvedValueOnce(jsonResponse(metaWithRowsUrl("/rows.ndjson", 1)))
          .mockResolvedValueOnce(textResponse("not-json")),
      }),
    ).rejects.toThrow("Invalid shooting record on line 1.");

    await expect(
      loadShootingRecords("https://api.example.test", 2026, {
        fetcher: vi
          .fn()
          .mockResolvedValueOnce(jsonResponse(metaWithRowsUrl("/rows.ndjson", 5)))
          .mockResolvedValueOnce(textResponse(rowsNdjson)),
      }),
    ).rejects.toThrow("Incomplete shooting records for 2026.");
  });

  it("refreshes a stale manifest once after a row 404 and never loops", async () => {
    const recoveringFetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(metaWithRowsUrl("/rows/version-1.ndjson")))
      .mockResolvedValueOnce(textResponse("", 404))
      .mockResolvedValueOnce(jsonResponse(metaWithRowsUrl("/rows/version-2.ndjson")))
      .mockResolvedValueOnce(textResponse(rowsNdjson));

    await expect(
      loadShootingRecords("https://api.example.test", 2026, {
        fetcher: recoveringFetcher,
      }),
    ).resolves.toMatchObject({ recordCount: 4 });
    expect(recoveringFetcher.mock.calls.map(([url]) => url)).toEqual([
      "https://api.example.test/shootings/meta",
      "https://api.example.test/rows/version-1.ndjson",
      "https://api.example.test/shootings/meta",
      "https://api.example.test/rows/version-2.ndjson",
    ]);

    const staleFetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(metaWithRowsUrl("/rows/version-1.ndjson")))
      .mockResolvedValueOnce(textResponse("", 404))
      .mockResolvedValueOnce(jsonResponse(metaWithRowsUrl("/rows/version-2.ndjson")))
      .mockResolvedValueOnce(textResponse("", 404));

    await expect(
      loadShootingRecords("https://api.example.test", 2026, {
        fetcher: staleFetcher,
      }),
    ).rejects.toThrow("Shooting records changed while loading 2026.");
    expect(staleFetcher).toHaveBeenCalledTimes(4);
  });
});

describe("shooting filter helpers", () => {
  it("derives date limits and preserves the legacy age-missing behavior", () => {
    const defaults = createShootingFilterState(shootingRows);
    expect(defaults).toEqual({
      age: [0, 100],
      dateInMs: [Date.UTC(2026, 0, 5), Date.UTC(2026, 3, 20)],
      excludeUnknownAge: false,
      fatalOnly: false,
      hasCourtCase: false,
      race: ["W", "B", "H", "A", "Other/Unknown"],
      sex: ["M", "F"],
      timeInMs: [0, 86_399_999],
      weekday: [0, 1, 2, 3, 4, 5, 6],
    });

    const filters = { ...defaults, age: [30, 60] as [number, number] };
    expect(filterShootingRows(shootingRows, filters)).toHaveLength(3);
    expect(
      filterShootingRows(
        shootingRows,
        { ...filters, excludeUnknownAge: true },
      ),
    ).toHaveLength(2);
  });

  it("matches the legacy boolean and category filter values", () => {
    const defaults = createShootingFilterState(shootingRows);
    expect(
      filterShootingRows(shootingRows, { ...defaults, fatalOnly: true }).map(
        (row) => row.dc_key,
      ),
    ).toEqual(["2026-01", "2026-03"]);
    expect(
      filterShootingRows(shootingRows, {
        ...defaults,
        hasCourtCase: true,
      }).map((row) => row.dc_key),
    ).toEqual(["2026-01", "2026-03"]);
    expect(
      filterShootingRows(shootingRows, { ...defaults, sex: ["F"] }).map(
        (row) => row.dc_key,
      ),
    ).toEqual(["2026-02"]);
    expect(
      filterShootingRows(shootingRows, { ...defaults, race: ["B"] }).map(
        (row) => row.dc_key,
      ),
    ).toEqual(["2026-01", "2026-04"]);
    expect(
      filterShootingRows(shootingRows, { ...defaults, weekday: [1] }).map(
        (row) => row.dc_key,
      ),
    ).toEqual(["2026-01", "2026-04"]);
    expect(
      filterShootingRows(shootingRows, {
        ...defaults,
        fatalOnly: true,
        hasCourtCase: true,
        race: ["B"],
        sex: ["M"],
        weekday: [1],
      }).map((row) => row.dc_key),
    ).toEqual(["2026-01"]);
    expect(
      filterShootingRows(shootingRows, { ...defaults, sex: [] }),
    ).toHaveLength(0);
  });

  it("excludes a histogram's own range while respecting other filters", () => {
    const defaults = createShootingFilterState(shootingRows);
    const filters = {
      ...defaults,
      age: [30, 40] as [number, number],
      sex: ["M"],
    };
    const ageHistogram = shootingHistogram(shootingRows, filters, "age");
    const timeHistogram = shootingHistogram(shootingRows, filters, "timeInMs");

    expect(ageHistogram).toHaveLength(30);
    expect(ageHistogram[0]?.x0).toBe(0);
    expect(ageHistogram.at(-1)?.x1).toBe(100);
    expect(ageHistogram.reduce((total, item) => total + item.length, 0)).toBe(2);
    expect(timeHistogram).toHaveLength(30);
    expect(timeHistogram[0]?.x0).toBe(0);
    expect(timeHistogram.at(-1)?.x1).toBe(86_399_999);
    expect(timeHistogram.reduce((total, item) => total + item.length, 0)).toBe(1);
    expect(hasActiveShootingFilters(filters, defaults)).toBe(true);
    expect(hasActiveShootingFilters(defaults, defaults)).toBe(false);
  });
});

describe("DashboardPointMap", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    maplibre.instances.length = 0;
    maplibre.popups.length = 0;
    routeQuery = {};
    routerReplace.mockReset();
    vi.stubGlobal("useRoute", () => mockedRoute);
    vi.stubGlobal("useRouter", () => ({ replace: routerReplace }));
    vi.stubGlobal(
      "matchMedia",
      vi.fn((media: string) => ({ matches: false, media })),
    );
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ type: "FeatureCollection", features: [] }),
          {
            headers: { "content-type": "application/json" },
            status: 200,
          },
        ),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("owns the MapLibre canvas description before style load and keeps it current", async () => {
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });

    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    expect(instance.addSource).not.toHaveBeenCalled();
    expect(instance.getCanvas().getAttribute("aria-label")).toBe(
      "Map showing 3 shooting-victim locations in Philadelphia for 2026",
    );
    expect(instance.getCanvas().getAttribute("aria-describedby")).toBe(
      "dashboard-point-map-description",
    );

    await wrapper.setProps({ records: recordResult([shootingRows[0]]) });
    expect(instance.addSource).not.toHaveBeenCalled();
    expect(instance.getCanvas().getAttribute("aria-label")).toBe(
      "Map showing 1 shooting-victim location in Philadelphia for 2026",
    );

    wrapper.unmount();
  });

  it("keeps exactly one fine-pointer attribution control across the width breakpoint and removes its resize listener", async () => {
    vi.stubGlobal("innerWidth", 390);
    const removeEventListener = vi.spyOn(window, "removeEventListener");
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });

    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    await vi.waitFor(() => expect(instance.addControl).toHaveBeenCalledTimes(4));
    const attributionControls = () =>
      instance
        .activeControls()
        .filter((control: Record<string, unknown>) =>
          control.kind === "attribution",
        );

    expect(maplibre.AttributionControl).toHaveBeenLastCalledWith({
      compact: true,
    });
    expect(attributionControls()).toHaveLength(1);

    vi.stubGlobal("innerWidth", 844);
    window.dispatchEvent(new Event("resize"));
    expect(instance.removeControl).toHaveBeenCalledTimes(1);
    expect(maplibre.AttributionControl).toHaveBeenLastCalledWith({
      compact: false,
    });
    expect(attributionControls()).toHaveLength(1);

    vi.stubGlobal("innerWidth", 820);
    window.dispatchEvent(new Event("resize"));
    expect(instance.removeControl).toHaveBeenCalledTimes(1);
    expect(maplibre.AttributionControl).toHaveBeenCalledTimes(2);

    vi.stubGlobal("innerWidth", 390);
    window.dispatchEvent(new Event("resize"));
    expect(instance.removeControl).toHaveBeenCalledTimes(2);
    expect(maplibre.AttributionControl).toHaveBeenLastCalledWith({
      compact: true,
    });
    expect(attributionControls()).toHaveLength(1);

    wrapper.unmount();
    expect(instance.activeControls()).toHaveLength(0);
    expect(
      removeEventListener.mock.calls.filter(([event]) => event === "resize"),
    ).toHaveLength(1);
    removeEventListener.mockRestore();
  });

  it("keeps a coarse-pointer phone attribution compact across orientation changes", async () => {
    vi.stubGlobal("innerWidth", 390);
    vi.stubGlobal(
      "matchMedia",
      vi.fn((media: string) => ({
        matches: media === "(pointer: coarse)",
        media,
      })),
    );
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });

    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    await vi.waitFor(() => expect(instance.addControl).toHaveBeenCalledTimes(4));
    expect(maplibre.AttributionControl).toHaveBeenLastCalledWith({
      compact: true,
    });

    vi.stubGlobal("innerWidth", 844);
    window.dispatchEvent(new Event("resize"));

    expect(instance.removeControl).not.toHaveBeenCalled();
    expect(maplibre.AttributionControl).toHaveBeenCalledTimes(1);
    expect(
      instance
        .activeControls()
        .filter(
          (control: Record<string, unknown>) =>
            control.kind === "attribution",
        ),
    ).toHaveLength(1);

    wrapper.unmount();
  });

  it("announces loaded and unmapped records, configures the point map, and cleans up", async () => {
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });
    expect(wrapper.get("#dashboard-point-map-description").text()).toContain(
      "Loading 2026 shooting-victim locations",
    );
    expect(
      wrapper.get("#dashboard-point-map-description").attributes("aria-live"),
    ).toBe("polite");
    expect(
      wrapper
        .get(".civic-dashboard-point-map__frame")
        .attributes("aria-busy"),
    ).toBe("true");

    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();
    await settleInitialMap(instance);

    expect(wrapper.text()).toContain(
      "Showing point locations for 3 of 4 shooting-victim records in 2026.",
    );
    expect(wrapper.text()).toContain(
      "1 record is not shown in the point layer because usable map coordinates are unavailable.",
    );
    await vi.waitFor(() =>
      expect(
        wrapper
          .get(".civic-dashboard-point-map__frame")
          .attributes("aria-busy"),
      ).toBe("false"),
    );
    const mapHost = wrapper.get(".civic-dashboard-point-map__canvas");
    expect(mapHost.attributes("aria-hidden")).toBe("false");
    // jsdom does not implement the reflected inert property, so Vue serializes
    // its false value instead of removing the attribute as modern browsers do.
    expect(mapHost.attributes("inert")).not.toBe("true");
    expect(instance.getCanvas().getAttribute("aria-label")).toBe(
      "Map showing 3 shooting-victim locations in Philadelphia for 2026",
    );
    expect(instance.getCanvas().getAttribute("aria-describedby")).toBe(
      "dashboard-point-map-description",
    );

    expect(maplibre.Map).toHaveBeenCalledWith(
      expect.objectContaining({
        attributionControl: false,
        center: [-75.1652, 39.9526],
        maxZoom: 18,
        minZoom: 9,
        preserveDrawingBuffer: true,
        zoom: 11,
      }),
    );
    expect(instance.addSource).toHaveBeenCalledWith(
      "shooting-records",
      expect.objectContaining({
        data: expect.objectContaining({
          features: expect.arrayContaining([
            expect.objectContaining({
              properties: expect.objectContaining({ fatal: true }),
            }),
            expect.objectContaining({
              properties: expect.objectContaining({ fatal: false }),
            }),
          ]),
        }),
        type: "geojson",
      }),
    );
    const layer = instance.addLayer.mock.calls
      .map(([candidate]: [Record<string, any>]) => candidate)
      .find(({ id }: Record<string, unknown>) => id === "shooting-record-points");
    expect(layer).toBeDefined();
    expect(layer.paint["circle-color"]).toEqual([
      "case",
      ["boolean", ["get", "fatal"], false],
      "#ff8a8a",
      "#e5dc8e",
    ]);
    expect(layer.paint["circle-radius"]).toEqual([
      "interpolate",
      ["exponential", 1.25],
      ["zoom"],
      10,
      3.5,
      16,
      11,
    ]);
    expect(layer.paint["circle-stroke-color"]).toEqual([
      "case",
      ["boolean", ["get", "fatal"], false],
      "#d84545",
      "#d3c913",
    ]);
    expect(layer.paint["circle-stroke-width"]).toBe(1);
    expect(instance.addControl.mock.calls.map((call: any[]) => call[1])).toEqual([
      "top-right",
      "top-right",
      "bottom-left",
      "bottom-right",
    ]);
    const homeControl = instance.addControl.mock.calls[1][0];
    const homeElement = homeControl.onAdd(instance) as HTMLElement;
    const homeButton = homeElement.querySelector("button");
    expect(homeButton?.getAttribute("aria-label")).toBe(
      "Reset map view to Philadelphia",
    );
    homeButton?.click();
    expect(instance.flyTo).toHaveBeenCalledWith({
      center: [-75.1652, 39.9526],
      duration: 1_000,
      zoom: 11,
    });
    homeControl.onRemove();

    instance.setView([-75.16, 39.95], 11.5);
    instance.triggerMoveEnd();
    expect(routerReplace).toHaveBeenCalledWith({
      query: {
        map: "11.50/39.95000/-75.16000",
        year: "2026",
      },
    });

    wrapper.unmount();
    expect(instance.remove).toHaveBeenCalledTimes(1);
  });

  it("exposes one indeterminate map progress status through initial, city, and MapLibre loading", async () => {
    const cityResponse = deferredResponse();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const url = new URL(input);
        if (url.pathname.endsWith("/boundaries/city_limits")) {
          return cityResponse.promise;
        }
        return Promise.resolve(
          jsonResponse({ type: "FeatureCollection", features: [] }),
        );
      }),
    );
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });
    const frame = wrapper.get(".civic-dashboard-point-map__frame");
    const progress = () =>
      wrapper.find('[role="progressbar"][aria-label="Loading map data"]');

    expect(progress().classes()).toContain("civic-dashboard-map-loading");
    expect(progress().attributes()).toMatchObject({
      "aria-valuemax": "100",
      "aria-valuemin": "0",
    });
    expect(progress().attributes("aria-valuenow")).toBeUndefined();
    expect(progress().attributes("aria-live")).toBeUndefined();
    expect(wrapper.findAll("[aria-live]")).toHaveLength(1);
    expect(frame.attributes("aria-busy")).toBe("true");

    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();
    await vi.waitFor(() =>
      expect(
        (fetch as ReturnType<typeof vi.fn>).mock.calls.some(([input]) =>
          new URL(input).pathname.endsWith("/boundaries/city_limits"),
        ),
      ).toBe(true),
    );

    expect(progress().exists()).toBe(true);
    expect(frame.attributes("aria-busy")).toBe("true");
    const mapHost = wrapper.get(".civic-dashboard-point-map__canvas");
    expect(mapHost.attributes("aria-hidden")).toBe("false");
    expect(mapHost.attributes("inert")).not.toBe("true");

    cityResponse.resolve(
      jsonResponse({ type: "FeatureCollection", features: [] }),
    );
    await vi.waitFor(() =>
      expect(instance.getLayer("city-limits-line")).toBeDefined(),
    );
    instance.triggerEvent("idle");
    await vi.waitFor(() => expect(progress().exists()).toBe(false));
    expect(frame.attributes("aria-busy")).toBe("false");

    instance.triggerEvent("dataloading");
    await nextTick();
    expect(progress().exists()).toBe(true);
    expect(frame.attributes("aria-busy")).toBe("true");
    expect(wrapper.findAll("[aria-live]")).toHaveLength(1);

    instance.triggerEvent("idle");
    await nextTick();
    expect(progress().exists()).toBe(false);
    expect(frame.attributes("aria-busy")).toBe("false");

    wrapper.unmount();
    expect(instance.activeEventListenerCount("dataloading")).toBe(0);
    expect(instance.activeEventListenerCount("idle")).toBe(0);
  });

  it("keeps the map interactive while boundary loading is pending and clears progress on success or error", async () => {
    const districtResponse = deferredResponse();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const url = new URL(input);
        if (url.pathname.endsWith("/boundaries/police_districts")) {
          return districtResponse.promise;
        }
        if (url.pathname.endsWith("/boundaries/zip_codes")) {
          return Promise.resolve(jsonResponse({}, 503));
        }
        return Promise.resolve(
          jsonResponse({ type: "FeatureCollection", features: [] }),
        );
      }),
    );
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();
    await settleInitialMap(instance);
    const progress = () => wrapper.find(".civic-dashboard-map-loading");
    const frame = wrapper.get(".civic-dashboard-point-map__frame");
    await vi.waitFor(() => expect(progress().exists()).toBe(false));

    await wrapper.setProps({ layers: ["police-districts"] });
    await vi.waitFor(() => expect(progress().exists()).toBe(true));
    expect(frame.attributes("aria-busy")).toBe("true");
    expect(wrapper.findAll("[data-map-legend]")).toHaveLength(0);
    expect(
      wrapper.get(".civic-dashboard-point-map__canvas").attributes("inert"),
    ).not.toBe("true");

    districtResponse.resolve(
      jsonResponse({ type: "FeatureCollection", features: [] }),
    );
    await vi.waitFor(() =>
      expect(instance.getLayer("shooting-boundary-fill")).toBeDefined(),
    );
    instance.triggerEvent("idle");
    await vi.waitFor(() => expect(progress().exists()).toBe(false));
    expect(frame.attributes("aria-busy")).toBe("false");
    expect(wrapper.findAll("[data-map-legend]")).toHaveLength(0);

    await wrapper.setProps({ layers: ["zip-codes"] });
    await vi.waitFor(() =>
      expect(wrapper.text()).toContain(
        "The selected geographic aggregation is temporarily unavailable.",
      ),
    );
    expect(progress().exists()).toBe(false);
    expect(frame.attributes("aria-busy")).toBe("false");
    expect(wrapper.findAll("[data-map-legend]")).toHaveLength(0);
    expect(
      wrapper.get(".civic-dashboard-map-print-button").attributes("disabled"),
    ).toBeDefined();
    expect(instance.getCanvas().getAttribute("aria-label")).toBe(
      "Map of Philadelphia with ZIP Codes aggregation unavailable for 2026",
    );

    wrapper.unmount();
  });

  it("shows progress as soon as street hot spots are scheduled and until their request settles", async () => {
    const streetResponse = deferredResponse();
    const fetcher = vi.fn((input: string) => {
      const url = new URL(input);
      if (url.pathname.endsWith("/streets")) return streetResponse.promise;
      return Promise.resolve(
        jsonResponse({ type: "FeatureCollection", features: [] }),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();
    await settleInitialMap(instance);
    const progress = () => wrapper.find(".civic-dashboard-map-loading");
    await vi.waitFor(() => expect(progress().exists()).toBe(false));

    await wrapper.setProps({
      layers: ["point-locations", "hot-spots-by-street-block"],
    });
    expect(progress().exists()).toBe(true);
    expect(wrapper.findAll("[data-map-legend]")).toHaveLength(0);
    expect(
      fetcher.mock.calls.some(([input]) =>
        new URL(input).pathname.endsWith("/streets"),
      ),
    ).toBe(false);
    await vi.waitFor(() =>
      expect(
        fetcher.mock.calls.some(([input]) =>
          new URL(input).pathname.endsWith("/streets"),
        ),
      ).toBe(true),
    );
    expect(progress().exists()).toBe(true);

    streetResponse.resolve(
      jsonResponse({ type: "FeatureCollection", features: [] }),
    );
    await vi.waitFor(() =>
      expect(instance.getLayer("shooting-street-hot-spots")).toBeDefined(),
    );
    instance.triggerEvent("idle");
    await vi.waitFor(() => expect(progress().exists()).toBe(false));
    expect(wrapper.findAll("[data-map-legend]")).toHaveLength(0);

    wrapper.unmount();
  });

  it("ignores stale loading events from a failed map after retrying", async () => {
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const failedInstance = maplibre.instances[0];
    failedInstance.addSource.mockImplementationOnce(() => {
      throw new Error("style failed");
    });
    failedInstance.triggerLoad();
    await vi.waitFor(() =>
      expect(wrapper.text()).toContain(
        "The interactive map is temporarily unavailable.",
      ),
    );
    expect(wrapper.find(".civic-dashboard-map-loading").exists()).toBe(false);

    await wrapper.get("button").trigger("click");
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(2));
    const activeInstance = maplibre.instances[1];
    activeInstance.triggerLoad();
    await settleInitialMap(activeInstance);
    await vi.waitFor(() =>
      expect(wrapper.find(".civic-dashboard-map-loading").exists()).toBe(false),
    );

    failedInstance.triggerEvent("dataloading");
    await nextTick();
    expect(wrapper.find(".civic-dashboard-map-loading").exists()).toBe(false);

    activeInstance.triggerEvent("dataloading");
    await nextTick();
    expect(wrapper.find(".civic-dashboard-map-loading").exists()).toBe(true);
    activeInstance.triggerEvent("idle");
    await nextTick();
    expect(wrapper.find(".civic-dashboard-map-loading").exists()).toBe(false);

    wrapper.unmount();
  });

  it("prints one composed map sheet without creating another map instance", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();
    await settleInitialMap(instance);
    vi.spyOn(instance.getCanvas(), "toDataURL").mockReturnValue(
      `data:image/png;base64,${"a".repeat(64)}`,
    );

    const printButton = wrapper.get(".civic-dashboard-map-print-button");
    expect(printButton.text()).toBe("Print map");
    expect(printButton.attributes("disabled")).toBeUndefined();

    instance.triggerEvent("dataloading");
    await nextTick();
    expect(printButton.attributes("disabled")).toBeDefined();
    await printButton.trigger("click");
    expect(print).not.toHaveBeenCalled();
    expect(
      document.body.querySelector(".civic-dashboard-map-print-sheet"),
    ).toBeNull();

    instance.triggerEvent("idle");
    await nextTick();
    expect(printButton.attributes("disabled")).toBeUndefined();
    await printButton.trigger("click");
    await vi.waitFor(() => expect(print).toHaveBeenCalledTimes(1));

    expect(maplibre.Map).toHaveBeenCalledTimes(1);
    expect(
      document.documentElement.classList.contains(
        "civic-dashboard-map-print-active",
      ),
    ).toBe(true);
    expect(
      document.body.classList.contains("civic-dashboard-map-print-active"),
    ).toBe(true);
    const sheet = document.body.querySelector<HTMLElement>(
      ".civic-dashboard-map-print-sheet",
    );
    expect(sheet).not.toBeNull();
    expect(sheet?.parentElement).toBe(document.body);
    const composedSvg = composedPrintSvg(sheet!);
    const printImage = sheet!.firstElementChild as HTMLImageElement;
    const printDescription = composedSvg.querySelector("desc")?.textContent;
    expect(composedSvg.getAttribute("width")).toBe("1450");
    expect(composedSvg.getAttribute("height")).toBe("1800");
    expect(composedSvg.querySelector("title")?.textContent).toBe(
      "Philadelphia shooting-victim map — 2026",
    );
    expect(composedSvg.textContent).toContain("Fatal — 1");
    expect(composedSvg.textContent).toContain("Nonfatal — 2");
    expect(composedSvg.querySelectorAll("[data-map-legend]")).toHaveLength(0);
    expect(printImage.alt).toBe(printDescription);
    expect(printImage.alt).toContain(
      "Showing point locations for 3 of 4 shooting-victim records in 2026.",
    );
    expect(printImage.alt).toContain("Fatal: 1. Nonfatal: 2.");
    expect(composedSvg.textContent).toContain(
      "Shooting-victim records: Philadelphia Police Department via OpenDataPhilly.",
    );
    expect(composedSvg.textContent).toContain("© OpenStreetMap contributors");
    expect(printImage.alt).toContain(
      "Shooting-victim records: Philadelphia Police Department via OpenDataPhilly.",
    );
    expect(printImage.alt).toContain("© OpenStreetMap contributors");

    window.dispatchEvent(new Event("afterprint"));
    await nextTick();
    expect(
      document.documentElement.classList.contains(
        "civic-dashboard-map-print-active",
      ),
    ).toBe(false);
    expect(
      document.body.classList.contains("civic-dashboard-map-print-active"),
    ).toBe(false);
    expect(
      document.body.querySelector(".civic-dashboard-map-print-sheet"),
    ).toBeNull();

    wrapper.unmount();
    expect(
      document.body.querySelector(".civic-dashboard-map-print-sheet"),
    ).toBeNull();
    print.mockRestore();
  });

  it("reports a print-image failure and never prints a blank sheet", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();
    await settleInitialMap(instance);
    vi.spyOn(instance.getCanvas(), "toDataURL").mockReturnValue("data:,");

    await wrapper.get(".civic-dashboard-map-print-button").trigger("click");
    await vi.waitFor(() =>
      expect(wrapper.get('[role="status"]').text()).toBe(
        "The map could not be prepared for printing.",
      ),
    );

    expect(print).not.toHaveBeenCalled();
    expect(
      document.body.querySelector(".civic-dashboard-map-print-sheet"),
    ).toBeNull();

    wrapper.unmount();
    print.mockRestore();
  });

  it("limits the map source and description when the fatal-only filter is active", async () => {
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: true,
        initialView: DEFAULT_MAP_VIEW,
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(shootingRows.filter((row) => row.fatal)),
        searchLocation: null,
        year: 2026,
      },
    });
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();
    await nextTick();

    expect(wrapper.text()).toContain(
      "Showing point locations for 1 of 2 fatal shooting-victim records in 2026.",
    );
    const source = instance.addSource.mock.calls[0][1];
    expect(source.data.features).toHaveLength(1);
    expect(
      source.data.features.every(
        (feature: { properties: { fatal: boolean } }) =>
          feature.properties.fatal,
      ),
    ).toBe(true);
    expect(instance.getCanvas().getAttribute("aria-label")).toBe(
      "Map showing 1 fatal shooting-victim location in Philadelphia for 2026",
    );

    wrapper.unmount();
    expect(instance.remove).toHaveBeenCalledTimes(1);
  });

  it("uses the smaller legacy All Years radius and updates it without rebuilding", async () => {
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(),
        searchLocation: null,
        year: null,
      },
    });
    expect(wrapper.text()).toContain(
      "Loading shooting-victim locations for all years",
    );
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();
    await nextTick();

    const pointLayer = instance.addLayer.mock.calls
      .map(([layer]: [Record<string, any>]) => layer)
      .find(({ id }: Record<string, unknown>) => id === "shooting-record-points");
    expect(pointLayer.paint["circle-radius"]).toEqual([
      "interpolate",
      ["exponential", 1.25],
      ["zoom"],
      10,
      1,
      16,
      9,
    ]);
    expect(wrapper.text()).toContain(
      "Showing point locations for 3 of 4 shooting-victim records across all years.",
    );
    expect(instance.getCanvas().getAttribute("aria-label")).toBe(
      "Map showing 3 shooting-victim locations in Philadelphia for all years",
    );

    await wrapper.setProps({ year: 2026 });
    expect(instance.setPaintProperty).toHaveBeenCalledWith(
      "shooting-record-points",
      "circle-radius",
      [
        "interpolate",
        ["exponential", 1.25],
        ["zoom"],
        10,
        3.5,
        16,
        11,
      ],
    );
    expect(maplibre.Map).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it.each([
    {
      description: "density",
      label:
        "Heat map showing the density of 3 shooting-victim locations in Philadelphia for 2026",
      layerIds: ["shooting-record-heat-map"],
      layers: ["heat-map"] as MapLayerId[],
      queryValue: "heat-map",
    },
    {
      description: "point locations and density",
      label:
        "Map showing point locations and density for 3 shooting-victim locations in Philadelphia for 2026",
      layerIds: ["shooting-record-heat-map", "shooting-record-points"],
      layers: ["point-locations", "heat-map"] as MapLayerId[],
      queryValue: "point-locations,heat-map",
    },
  ])(
    "renders $description from the existing point source",
    async ({ description, label, layerIds, layers, queryValue }) => {
      const wrapper = mount(DashboardPointMap, {
        props: {
          apiBaseUrl: "https://api.example.test",
          boundaryOpacity: 0.5,
          fatalOnly: false,
          initialView: DEFAULT_MAP_VIEW,
          layers,
          records: recordResult(),
          searchLocation: null,
          year: 2026,
        },
      });
      await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
      const instance = maplibre.instances[0];
      instance.triggerLoad();
      await nextTick();

      expect(instance.addSource).toHaveBeenCalledWith(
        "shooting-records",
        expect.any(Object),
      );
      const dataLayers = instance.addLayer.mock.calls
        .map(([layer]: [Record<string, unknown>]) => layer)
        .filter(({ id }: Record<string, unknown>) =>
          String(id).startsWith("shooting-record-"),
        );
      expect(dataLayers.map(({ id }: Record<string, unknown>) => id)).toEqual(
        ["shooting-record-heat-map", "shooting-record-points"],
      );
      expect(
        dataLayers
          .filter(
            ({ layout }: Record<string, any>) =>
              layout?.visibility === "visible",
          )
          .map(({ id }: Record<string, unknown>) => id),
      ).toEqual(layerIds);
      const heatLayer = dataLayers.find(
        ({ id }: Record<string, unknown>) => id === "shooting-record-heat-map",
      );
      expect(heatLayer).toBeDefined();
      expect(heatLayer.type).toBe("heatmap");
      expect(heatLayer.paint["heatmap-color"]).toEqual([
        "interpolate",
        ["linear"],
        ["heatmap-density"],
        0,
        "rgba(0, 0, 0, 0)",
        0.1,
        "#120d31",
        0.2,
        "#331067",
        0.3,
        "#59157e",
        0.4,
        "#7e2482",
        0.5,
        "#a3307e",
        0.6,
        "#c83e73",
        0.7,
        "#e95462",
        0.8,
        "#fa7d5e",
        0.9,
        "#fea973",
        1,
        "#fed395",
      ]);
      expect(heatLayer.layout.visibility).toBe(
        layers.includes("heat-map") ? "visible" : "none",
      );
      const pointLayer = dataLayers.find(
        ({ id }: Record<string, unknown>) => id === "shooting-record-points",
      );
      expect(pointLayer?.layout.visibility).toBe(
        layers.includes("point-locations") ? "visible" : "none",
      );
      expect(wrapper.text()).toContain(
        `Showing ${description} for 3 of 4 shooting-victim records in 2026.`,
      );
      expect(instance.getCanvas().getAttribute("aria-label")).toBe(label);

      instance.setView([-75.16, 39.95], 11.5);
      instance.triggerMoveEnd();
      expect(routerReplace).toHaveBeenCalledWith({
        query: {
          layers: queryValue,
          map: "11.50/39.95000/-75.16000",
          year: "2026",
        },
      });

      wrapper.unmount();
      expect(instance.remove).toHaveBeenCalledTimes(1);
    },
  );

  it("shows safe legacy hover and pinned point popups and removes its listeners", async () => {
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();
    await nextTick();

    const pointEvent = {
      features: [
        {
          properties: {
            age: 24,
            date: "2026-01-05",
            dcKey: "2026-01",
            fatal: true,
            hasCourtCase: null,
            race: "B",
            sex: "M",
            streetBlock: '1200 block of <img src="x" onerror="alert(1)">',
            timeInMs: 3_600_000,
          },
        },
      ],
      lngLat: { lat: 39.9526, lng: -75.1602 },
    };
    instance.triggerLayerEvent(
      "mouseenter",
      "shooting-record-points",
      pointEvent,
    );
    expect(instance.getCanvas().style.cursor).toBe("pointer");
    expect(maplibre.Popup).toHaveBeenCalledWith(
      expect.objectContaining({
        className: "civic-dashboard-point-popup",
        closeButton: false,
        closeOnClick: false,
        maxWidth: "320px",
      }),
    );
    const hoverPopup = maplibre.popups[0];
    expect(hoverPopup.setLngLat).toHaveBeenCalledWith(pointEvent.lngLat);
    const content = hoverPopup.setDOMContent.mock.calls[0][0] as HTMLElement;
    expect(content.getAttribute("aria-label")).toBe(
      "Shooting incident details",
    );
    expect(content.querySelector(".civic-map-tooltip__badge")?.tagName).toBe(
      "SPAN",
    );
    expect(content.textContent).toContain("Fatal");
    expect(content.textContent).toContain("Mon, Jan 5, 2026");
    expect(content.textContent).toContain("1:00 AM");
    expect(content.textContent).toContain(
      '1200 <img src="x" onerror="alert(1)">',
    );
    expect(content.textContent).not.toContain("block of");
    expect(content.textContent).toContain("Victim Information");
    expect(content.textContent).toContain("Case Information");
    expect(content.textContent).toContain("Court search resultUnknown");
    expect(content.textContent).not.toContain(
      "Nearest-street context; not an exact address.",
    );
    expect(
      Array.from(
        content.querySelectorAll(".civic-map-tooltip__section-heading"),
        (element) => element.textContent,
      ),
    ).toEqual(["Victim Information", "Case Information"]);
    expect(content.querySelectorAll(".civic-map-tooltip__row")).toHaveLength(
      8,
    );
    expect(content.querySelector("img")).toBeNull();

    instance.triggerLayerEvent("mouseleave", "shooting-record-points");
    expect(instance.getCanvas().style.cursor).toBe("");
    expect(hoverPopup.remove).toHaveBeenCalledTimes(1);

    instance.triggerLayerEvent("click", "shooting-record-points", pointEvent);
    expect(maplibre.Popup).toHaveBeenLastCalledWith(
      expect.objectContaining({
        className:
          "civic-dashboard-point-popup civic-dashboard-point-popup--pinned",
        closeButton: true,
        closeOnClick: false,
        maxWidth: "320px",
      }),
    );
    const pinnedPopup = maplibre.popups[1];
    expect(pinnedPopup.on).toHaveBeenCalledWith("close", expect.any(Function));
    instance.triggerLayerEvent(
      "mouseenter",
      "shooting-record-points",
      pointEvent,
    );
    expect(maplibre.Popup).toHaveBeenCalledTimes(2);

    wrapper.unmount();
    expect(pinnedPopup.remove).toHaveBeenCalledTimes(1);
    for (const event of ["click", "mouseenter", "mouseleave"]) {
      expect(instance.off).toHaveBeenCalledWith(
        event,
        "shooting-record-points",
        expect.any(Function),
      );
    }
    expect(instance.remove).toHaveBeenCalledTimes(1);
  });

  it("starts from a shared view and replaces the URL after a map move", async () => {
    routeQuery = {
      fresh: "1",
      layers: "legacy-layer",
      map: "12.76/39.97240/-75.14142",
      utm_source: "newsletter",
      year: "2026",
    };

    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: true,
        initialView: {
          center: [-75.14142, 39.9724],
          zoom: 12.76,
        },
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(shootingRows.filter((row) => row.fatal)),
        searchLocation: null,
        year: 2026,
      },
    });
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    expect(instance.options).toEqual(
      expect.objectContaining({ center: [-75.14142, 39.9724], zoom: 12.76 }),
    );
    instance.triggerLoad();
    await nextTick();

    instance.setView([-75.151234, 39.961234], 13.456);
    instance.triggerMoveEnd();
    expect(routerReplace).toHaveBeenCalledWith({
      query: {
        fresh: "1",
        map: "13.46/39.96123/-75.15123",
        utm_source: "newsletter",
        year: "2026",
      },
    });

    routeQuery = {
      fresh: "1",
      map: "13.46/39.96123/-75.15123",
      utm_source: "newsletter",
      year: "2026",
    };
    instance.triggerMoveEnd();
    expect(routerReplace).toHaveBeenCalledTimes(1);

    wrapper.unmount();
    expect(instance.off).toHaveBeenCalledWith("moveend", expect.any(Function));
    expect(instance.remove).toHaveBeenCalledTimes(1);
  });

  it("restores a changed URL view without rebuilding the map", async () => {
    routeQuery = {
      map: "12.00/39.95000/-75.16000",
      year: "2026",
    };

    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: { center: [-75.16, 39.95], zoom: 12 },
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();
    await nextTick();

    routeQuery = {
      map: "13.25/39.97000/-75.14000",
      year: "2026",
    };
    await wrapper.setProps({
      initialView: { center: [-75.14, 39.97], zoom: 13.25 },
    });

    expect(instance.jumpTo).toHaveBeenCalledWith({
      center: [-75.14, 39.97],
      zoom: 13.25,
    });
    expect(maplibre.Map).toHaveBeenCalledTimes(1);
    instance.triggerMoveEnd();
    expect(routerReplace).not.toHaveBeenCalled();

    wrapper.unmount();
  });

  it("updates filtered locations without rebuilding the map", async () => {
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: DEFAULT_MAP_LAYERS,
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();
    await nextTick();
    const source = instance.getSource("shooting-records");
    const filtered = recordResult(shootingRows.slice(0, 2));
    await wrapper.setProps({ records: filtered });

    expect(source.setData).toHaveBeenCalledWith(filtered.points);
    expect(maplibre.Map).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain(
      "Showing point locations for 2 of 2 shooting-victim records in 2026.",
    );
    wrapper.unmount();
  });

  it("switches point and heat visibility without remounting the map", async () => {
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: ["point-locations"],
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();
    await nextTick();

    expect(instance.getLayer("shooting-record-points").layout.visibility).toBe(
      "visible",
    );
    expect(
      instance.getLayer("shooting-record-heat-map").layout.visibility,
    ).toBe("none");

    await wrapper.setProps({ layers: ["heat-map"] });
    expect(instance.setLayoutProperty.mock.calls).toEqual(
      expect.arrayContaining([
        ["shooting-record-points", "visibility", "none"],
        ["shooting-record-heat-map", "visibility", "visible"],
      ]),
    );
    expect(maplibre.Map).toHaveBeenCalledTimes(1);
    expect(instance.remove).not.toHaveBeenCalled();

    wrapper.unmount();
    expect(instance.remove).toHaveBeenCalledTimes(1);
  });

  it("refreshes a boundary scale, legend, and interaction when the geography changes", async () => {
    const aggregateRows = [
      { ...shootingRows[0], dc_key: "district-6-a" },
      { ...shootingRows[0], dc_key: "district-6-b" },
      { ...shootingRows[0], dc_key: "district-6-c" },
      shootingRows[1],
      shootingRows[2],
    ] as ShootingRow[];
    const overlayFetch = vi.fn((input: string) => {
      const url = new URL(input);
      if (url.pathname.endsWith("/boundaries/police_districts")) {
        return Promise.resolve(
          jsonResponse({
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                geometry: { type: "Point", coordinates: [-75.16, 39.95] },
                properties: { police_district: "6" },
              },
              {
                type: "Feature",
                geometry: { type: "Point", coordinates: [-75.17, 39.96] },
                properties: { police_district: "9" },
              },
            ],
          }),
        );
      }
      if (url.pathname.endsWith("/boundaries/zip_codes")) {
        return Promise.resolve(
          jsonResponse({
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                geometry: { type: "Point", coordinates: [-75.16, 39.95] },
                properties: { zip_code: "19107" },
              },
              {
                type: "Feature",
                geometry: { type: "Point", coordinates: [-75.17, 39.96] },
                properties: { zip_code: "19103" },
              },
            ],
          }),
        );
      }
      return Promise.resolve(
        jsonResponse({ type: "FeatureCollection", features: [] }),
      );
    });
    vi.stubGlobal("fetch", overlayFetch);
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: ["police-districts"],
        records: recordResult(aggregateRows),
        searchLocation: null,
        year: 2026,
      },
    });
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();

    await vi.waitFor(() =>
      expect(instance.getLayer("shooting-boundary-fill")).toBeDefined(),
    );
    instance.triggerEvent("idle");
    await nextTick();
    const source = instance.getSource("shooting-boundary");
    expect(source.data.features[0].properties).toEqual(
      expect.objectContaining({ fatal: 3, nonfatal: 0, total_shootings: 3 }),
    );
    expect(instance.addLayer).toHaveBeenCalledWith(
      expect.objectContaining({ id: "shooting-boundary-fill", type: "fill" }),
      "shooting-record-heat-map",
    );
    expect(wrapper.text()).toContain(
      "Showing 4 of 5 shooting-victim records aggregated by Police Districts in 2026.",
    );
    expect(wrapper.text()).toContain(
      "1 record is not shown in this layer because a matching police district is unavailable.",
    );
    expect(instance.getCanvas().getAttribute("aria-label")).toBe(
      "Map showing 4 of 5 shooting-victim records aggregated by Police Districts in Philadelphia for 2026",
    );

    const districtEvent = {
      features: [
        {
          properties: {
            fatal: 3,
            nonfatal: 0,
            police_district: "6",
            total_shootings: 3,
          },
        },
      ],
      lngLat: { lat: 39.95, lng: -75.16 },
    };
    instance.triggerLayerEvent(
      "mousemove",
      "shooting-boundary-fill",
      districtEvent,
    );
    const districtHoverPopup = maplibre.popups[0];
    expect(maplibre.Popup).toHaveBeenCalledWith(
      expect.objectContaining({
        className: "map-tooltip-popup",
        closeButton: false,
        closeOnClick: false,
        maxWidth: "320px",
      }),
    );
    expect(districtHoverPopup.setLngLat).toHaveBeenCalledWith(
      districtEvent.lngLat,
    );
    expect(instance.getCanvas().style.cursor).toBe("");
    const districtHoverContent = districtHoverPopup.setDOMContent.mock
      .calls[0][0] as HTMLElement;
    expect(districtHoverContent.querySelector(".tooltip-title")?.textContent).toBe(
      "Police District #6",
    );
    expect(
      districtHoverContent.querySelector(".tooltip-stat-value")?.textContent,
    ).toBe("3");
    expect(
      districtHoverContent.querySelector(".tooltip-stat-label")?.textContent,
    ).toBe("shooting victims");
    expect(districtHoverContent.textContent).not.toContain("Fatal");
    expect(districtHoverContent.textContent).not.toContain("Nonfatal");
    expect(wrapper.find(".civic-dashboard-map-selection").exists()).toBe(false);
    expect(wrapper.text()).not.toContain(
      "Select an area or street block to review its filtered counts.",
    );

    instance.triggerLayerEvent("click", "shooting-boundary-fill", districtEvent);
    const districtPinnedPopup = maplibre.popups[1];
    expect(districtHoverPopup.remove).toHaveBeenCalled();
    expect(districtPinnedPopup.options).toEqual(
      expect.objectContaining({
        className: "map-tooltip-popup map-tooltip-popup--pinned",
        closeButton: true,
        closeOnClick: false,
        maxWidth: "320px",
      }),
    );
    expect(districtPinnedPopup.on).toHaveBeenCalledWith(
      "close",
      expect.any(Function),
    );

    const legendName = () =>
      wrapper
        .get('[data-map-legend="choropleth"]')
        .attributes("aria-label");
    expect(legendName()).toContain("from 1 to 3");
    const liveLegend = legendContract(wrapper.element, "choropleth");
    expect(liveLegend).toEqual({
      accessibleName:
        "Shooting victims by police district map legend. Darker red means more victims. Gray means no matching victims. Linear scale from 1 to 3. Counts reflect the current filters.",
      barStyle: expect.stringContaining("rgb(255, 245, 240) 0%"),
      key:
        "Gray: no matching victims. Darker red means more victims. Counts reflect the current filters.",
      scale: "linear",
      ticks: [
        { label: "1", left: "0%", value: "1" },
        { label: "2", left: "50%", value: "2" },
        { label: "3", left: "100%", value: "3" },
      ],
      title: "Shooting victims by police district",
      zero: "0",
      zeroColor: "background-color: rgb(104, 113, 118);",
    });
    expect(liveLegend?.barStyle).toContain("rgb(103, 0, 13) 100%");
    const boundaryPaint = JSON.stringify(
      instance.getLayer("shooting-boundary-fill").paint["fill-color"],
    );
    expect(boundaryPaint).toContain('"#687176"');
    expect(boundaryPaint).toContain('"rgb(255, 245, 240)"');
    expect(boundaryPaint).toContain('"rgb(103, 0, 13)"');
    expect(boundaryPaint).not.toContain('"ln"');

    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    vi.spyOn(instance.getCanvas(), "toDataURL").mockReturnValue(
      `data:image/png;base64,${"b".repeat(64)}`,
    );
    await wrapper.get(".civic-dashboard-map-print-button").trigger("click");
    await vi.waitFor(() => expect(print).toHaveBeenCalledTimes(1));
    const printSheet = document.body.querySelector<HTMLElement>(
      ".civic-dashboard-map-print-sheet",
    );
    expect(printSheet).not.toBeNull();
    const composedSvg = composedPrintSvg(printSheet!);
    const printImage = printSheet!.firstElementChild as HTMLImageElement;
    expect(composedSvg.textContent).toContain(liveLegend?.title);
    expect(composedSvg.textContent).toContain(
      "Darker red means more victims. Linear scale.",
    );
    expect(composedSvg.innerHTML).toContain("rgb(255, 245, 240)");
    expect(composedSvg.innerHTML).toContain("rgb(103, 0, 13)");
    expect(
      Array.from(
        composedSvg.querySelectorAll("text"),
        (text) => text.textContent,
      ),
    ).toContain("0 — No matching victims");
    expect(composedSvg.textContent).not.toContain(
      "Shooting victims per street block",
    );
    expect(printImage.alt).toBe(
      composedSvg.querySelector("desc")?.textContent,
    );
    expect(printImage.alt).toContain(
      "Showing 4 of 5 shooting-victim records aggregated by Police Districts in 2026.",
    );
    expect(printImage.alt).toContain(liveLegend?.accessibleName);
    expect(printImage.alt).toContain(
      "Shooting-victim records: Philadelphia Police Department via OpenDataPhilly.",
    );
    expect(printImage.alt).toContain("© OpenStreetMap contributors");
    window.dispatchEvent(new Event("afterprint"));
    await nextTick();
    print.mockRestore();

    await wrapper.setProps({ layers: ["zip-codes"] });
    await vi.waitFor(() => expect(source.setData).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(maplibre.popups).toHaveLength(3));
    expect(districtPinnedPopup.remove).toHaveBeenCalled();
    instance.triggerLayerEvent("mousemove", "shooting-boundary-fill", {
      features: [
        {
          properties: {
            fatal: 3,
            nonfatal: 0,
            total_shootings: 3,
            zip_code: "19107",
          },
        },
      ],
      lngLat: { lat: 39.95, lng: -75.16 },
    });
    const zipContent = maplibre.popups[2].setDOMContent.mock
      .calls[0][0] as HTMLElement;
    expect(zipContent.querySelector(".tooltip-title")?.textContent).toBe(
      "19107",
    );
    for (const event of ["click", "mousemove", "mouseleave"]) {
      expect(
        instance.activeLayerListenerCount(event, "shooting-boundary-fill"),
      ).toBe(1);
    }
    expect(maplibre.Map).toHaveBeenCalledTimes(1);

    instance.setPaintProperty.mockClear();
    await wrapper.setProps({ records: recordResult([shootingRows[1]]) });
    await vi.waitFor(() =>
      expect(instance.setPaintProperty).toHaveBeenCalledWith(
        "shooting-boundary-fill",
        "fill-color",
        [
          "case",
          ["==", ["get", "total_shootings"], 0],
          "#687176",
          "rgb(249, 105, 76)",
        ],
      ),
    );
    expect(legendContract(wrapper.element, "choropleth")).toEqual({
      accessibleName:
        "Shooting victims by ZIP code map legend. 1 shooting victim. Gray means no matching victims. Counts reflect the current filters.",
      barStyle: "background: rgb(249, 105, 76);",
      key:
        "Gray: no matching victims. 1 shooting victim. Counts reflect the current filters.",
      scale: "linear",
      ticks: [{ label: "1", left: "50%", value: "1" }],
      title: "Shooting victims by ZIP code",
      zero: "0",
      zeroColor: "background-color: rgb(104, 113, 118);",
    });

    await wrapper.setProps({ layers: [] });
    await vi.waitFor(() =>
      expect(
        wrapper.find('[role="img"][aria-label*="Total Shooting Victims"]')
          .exists(),
      ).toBe(false),
    );
    wrapper.unmount();
    expect(instance.off).toHaveBeenCalledWith(
      "click",
      "shooting-boundary-fill",
      expect.any(Function),
    );
  });

  it("updates the street hot-spot scale and legend without replacing point locations", async () => {
    const aggregateRows = [
      { ...shootingRows[0], dc_key: "segment-1-a" },
      { ...shootingRows[0], dc_key: "segment-1-b" },
      { ...shootingRows[0], dc_key: "segment-1-c" },
      shootingRows[1],
      {
        ...shootingRows[2],
        dc_key: "missing-segment-with-coordinates",
        lat: 39.97,
        lon: -75.14,
      },
    ] as ShootingRow[];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const url = new URL(input);
        if (url.pathname.endsWith("/streets")) {
          const ids = url.searchParams.get("segment_ids")?.split(",") ?? [];
          return Promise.resolve(
            jsonResponse({
              type: "FeatureCollection",
              features: ids.map((id) => ({
                type: "Feature",
                geometry: { type: "LineString", coordinates: [] },
                properties: {
                  block_label:
                    id === "segment-1"
                      ? "1200 BLOCK MARKET ST"
                      : "500 BLOCK BROAD ST",
                  block_number: id === "segment-1" ? 1200 : 500,
                  segment_id: id,
                  street_name: id === "segment-1" ? "MARKET ST" : "BROAD ST",
                },
              })),
            }),
          );
        }
        return Promise.resolve(
          jsonResponse({ type: "FeatureCollection", features: [] }),
        );
      }),
    );
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: [
          "point-locations",
          "heat-map",
          "hot-spots-by-street-block",
        ],
        records: recordResult(aggregateRows),
        searchLocation: null,
        year: 2026,
      },
    });
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();

    await vi.waitFor(() =>
      expect(instance.getLayer("shooting-street-hot-spots")).toBeDefined(),
    );
    instance.triggerEvent("idle");
    await nextTick();
    expect(instance.getLayer("shooting-record-points")).toBeDefined();
    const source = instance.getSource("shooting-streets");
    expect(source.data.features).toHaveLength(2);
    expect(source.data.features[0].properties).toEqual(
      expect.objectContaining({ total_shootings: 3 }),
    );
    expect(wrapper.text()).toContain(
      "Showing point locations and density for 5 of 5 shooting-victim records in 2026.",
    );
    expect(wrapper.text()).toContain(
      "Street-block hot spots represent 4 of 5 shooting-victim records in 2026.",
    );
    expect(wrapper.text()).toContain(
      "1 record is not shown in the street-block layer because a matching street block is unavailable.",
    );
    expect(instance.getCanvas().getAttribute("aria-label")).toBe(
      "Map showing point locations and density for 5 shooting-victim locations, with street-block hot spots for 4 of 5 records, in Philadelphia for 2026",
    );
    const legendName = () =>
      wrapper
        .get('[data-map-legend="street-hot-spots"]')
        .attributes("aria-label");
    expect(legendName()).toContain("from 1 to 3");
    const liveLegend = legendContract(wrapper.element, "street-hot-spots");
    expect(liveLegend).toEqual({
      accessibleName:
        "Shooting victims per street block map legend. Brighter yellow means more victims. Logarithmic scale from 1 to 3. Counts reflect the current filters.",
      barStyle: expect.stringContaining("#cc4778 0%"),
      key:
        "Brighter yellow means more victims. Counts reflect the current filters.",
      scale: "log",
      ticks: [
        { label: "1", left: "0%", value: "1" },
        {
          label: "2",
          left: expect.stringMatching(/^63\.09/),
          value: "2",
        },
        { label: "3", left: "100%", value: "3" },
      ],
      title: "Shooting victims per street block",
      zero: undefined,
      zeroColor: undefined,
    });
    expect(liveLegend?.barStyle).toContain("#f0f921 100%");
    const streetPaint = JSON.stringify(
      instance.getLayer("shooting-street-hot-spots").paint["line-color"],
    );
    expect(streetPaint).toContain('"ln"');
    expect(streetPaint).toContain('"#cc4778"');
    expect(streetPaint).toContain('"#f0f921"');

    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    vi.spyOn(instance.getCanvas(), "toDataURL").mockReturnValue(
      `data:image/png;base64,${"c".repeat(64)}`,
    );
    await wrapper.get(".civic-dashboard-map-print-button").trigger("click");
    await vi.waitFor(() => expect(print).toHaveBeenCalledTimes(1));
    const printSheet = document.body.querySelector<HTMLElement>(
      ".civic-dashboard-map-print-sheet",
    );
    expect(printSheet).not.toBeNull();
    const composedSvg = composedPrintSvg(printSheet!);
    const printImage = printSheet!.firstElementChild as HTMLImageElement;
    expect(composedSvg.textContent).toContain("Fatal — 4");
    expect(composedSvg.textContent).toContain("Nonfatal — 1");
    expect(composedSvg.textContent).toContain(
      "Density: brighter areas indicate a greater concentration of mapped records.",
    );
    expect(composedSvg.textContent).toContain(liveLegend?.title);
    expect(composedSvg.textContent).toContain(
      "Brighter yellow means more victims. Logarithmic scale.",
    );
    expect(composedSvg.innerHTML).toContain("#cc4778");
    expect(composedSvg.innerHTML).toContain("#f0f921");
    expect(composedSvg.textContent).not.toContain(
      "Shooting victims by police district",
    );
    expect(printImage.alt).toBe(
      composedSvg.querySelector("desc")?.textContent,
    );
    expect(printImage.alt).toContain(
      "Showing point locations and density for 5 of 5 shooting-victim records in 2026.",
    );
    expect(printImage.alt).toContain("Fatal: 4. Nonfatal: 1.");
    expect(printImage.alt).toContain(liveLegend?.accessibleName);
    expect(printImage.alt).toContain(
      "Shooting-victim records: Philadelphia Police Department via OpenDataPhilly.",
    );
    expect(printImage.alt).toContain("© OpenStreetMap contributors");
    window.dispatchEvent(new Event("afterprint"));
    await nextTick();
    print.mockRestore();

    const streetEvent = {
      features: [{ properties: source.data.features[0].properties }],
      lngLat: { lat: 39.95, lng: -75.16 },
    };
    instance.triggerLayerEvent(
      "mousemove",
      "shooting-street-hot-spots",
      streetEvent,
    );
    const streetHoverPopup = maplibre.popups[0];
    const streetHoverContent = streetHoverPopup.setDOMContent.mock
      .calls[0][0] as HTMLElement;
    expect(streetHoverContent.querySelector(".tooltip-title")?.textContent).toBe(
      "1200 MARKET ST",
    );
    expect(streetHoverContent.textContent).not.toContain("BLOCK");
    expect(
      streetHoverContent.querySelector(".tooltip-stat-value")?.textContent,
    ).toBe("3");
    expect(
      streetHoverContent.querySelector(".tooltip-stat-label")?.textContent,
    ).toBe("shooting victims");
    expect(streetHoverPopup.setLngLat).toHaveBeenCalledWith(streetEvent.lngLat);
    expect(instance.getCanvas().style.cursor).toBe("");

    instance.triggerLayerEvent(
      "click",
      "shooting-street-hot-spots",
      streetEvent,
    );
    const firstStreetPinnedPopup = maplibre.popups[1];
    expect(firstStreetPinnedPopup.options).toEqual(
      expect.objectContaining({
        className: "map-tooltip-popup map-tooltip-popup--pinned",
        closeButton: true,
      }),
    );
    instance.triggerLayerEvent("click", "shooting-record-points", {
      features: [
        {
          properties: {
            age: 24,
            date: "2026-01-05",
            dcKey: "2026-01",
            fatal: true,
            hasCourtCase: true,
            race: "B",
            sex: "M",
            streetBlock: "1200 block of MARKET ST",
            timeInMs: 3_600_000,
          },
        },
      ],
      lngLat: streetEvent.lngLat,
    });
    const pointPinnedPopup = maplibre.popups[2];
    expect(firstStreetPinnedPopup.remove).toHaveBeenCalled();
    instance.triggerLayerEvent(
      "click",
      "shooting-street-hot-spots",
      streetEvent,
    );
    const streetPinnedPopup = maplibre.popups[3];
    expect(pointPinnedPopup.remove).toHaveBeenCalled();
    const hoverUpdates = streetHoverPopup.setDOMContent.mock.calls.length;
    instance.triggerLayerEvent(
      "mousemove",
      "shooting-street-hot-spots",
      streetEvent,
    );
    expect(streetHoverPopup.setDOMContent).toHaveBeenCalledTimes(hoverUpdates);

    instance.setPaintProperty.mockClear();
    await wrapper.setProps({ records: recordResult([shootingRows[1]]) });
    await vi.waitFor(() =>
      expect(instance.setPaintProperty).toHaveBeenCalledWith(
        "shooting-street-hot-spots",
        "line-color",
        "#f89540",
      ),
    );
    expect(source.setData).toHaveBeenCalled();
    expect(legendContract(wrapper.element, "street-hot-spots")).toEqual({
      accessibleName:
        "Shooting victims per street block map legend. 1 shooting victim. Counts reflect the current filters.",
      barStyle: "background: rgb(248, 149, 64);",
      key: "1 shooting victim. Counts reflect the current filters.",
      scale: "log",
      ticks: [{ label: "1", left: "50%", value: "1" }],
      title: "Shooting victims per street block",
      zero: undefined,
      zeroColor: undefined,
    });
    expect(maplibre.Map).toHaveBeenCalledTimes(1);

    await wrapper.setProps({ layers: ["point-locations"] });
    await vi.waitFor(() =>
      expect(
        wrapper.find('[role="img"][aria-label*="Total Shooting Victims"]')
          .exists(),
      ).toBe(false),
    );
    await vi.waitFor(() =>
      expect(streetPinnedPopup.remove).toHaveBeenCalled(),
    );
    expect(instance.off).toHaveBeenCalledWith(
      "mousemove",
      "shooting-street-hot-spots",
      expect.any(Function),
    );
    wrapper.unmount();
  });

  it("centers an address marker and honestly supports an empty data-layer selection", async () => {
    const wrapper = mount(DashboardPointMap, {
      props: {
        apiBaseUrl: "https://api.example.test",
        boundaryOpacity: 0.5,
        fatalOnly: false,
        initialView: DEFAULT_MAP_VIEW,
        layers: [],
        records: recordResult(),
        searchLocation: null,
        year: 2026,
      },
    });
    await vi.waitFor(() => expect(maplibre.Map).toHaveBeenCalledTimes(1));
    const instance = maplibre.instances[0];
    instance.triggerLoad();
    await nextTick();

    expect(wrapper.text()).toContain("No shooting data layer is selected");
    expect(instance.getCanvas().getAttribute("aria-label")).toBe(
      "Map of Philadelphia with no shooting data layer selected for 2026",
    );
    await wrapper.setProps({
      searchLocation: {
        displayName: "City Hall, Philadelphia",
        id: 1,
        lat: 39.9526,
        lon: -75.1636,
        shortName: "City Hall",
      },
    });

    expect(instance.getSource("address-search-location").setData).toHaveBeenCalledWith(
      expect.objectContaining({
        features: [
          expect.objectContaining({
            geometry: {
              type: "Point",
              coordinates: [-75.1636, 39.9526],
            },
          }),
        ],
      }),
    );
    expect(instance.flyTo).toHaveBeenCalledWith({
      center: [-75.1636, 39.9526],
      duration: 1_500,
      zoom: 16,
    });
    expect(wrapper.text()).toContain("Centered on City Hall");
    wrapper.unmount();
  });
});
