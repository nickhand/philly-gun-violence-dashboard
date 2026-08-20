import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import DashboardAddressSearch from "../../../app/components/DashboardAddressSearch.vue";
import DashboardCategoryCharts from "../../../app/components/DashboardCategoryCharts.vue";
import DashboardDownloadPanel from "../../../app/components/DashboardDownloadPanel.vue";
import CivicIcon from "../../../layers/civic-ui/app/components/CivicIcon.vue";
import { searchPhiladelphiaAddresses } from "../../../app/utils/geocoding";
import {
  boundaryOverlayConfig,
  fetchStreetHotSpots,
  joinBoundaryCounts,
} from "../../../app/utils/mapOverlays";
import {
  aggregateShootingRows,
  createShootingDownload,
  featuresToCsv,
  rowsToExportFeatures,
} from "../../../app/utils/shootingDownloads";
import type { ShootingRow } from "../../../app/utils/shootingRecords";
import { shootingRows } from "../../fixtures/shootings";

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    headers: { "content-type": "application/json" },
    status,
  });
}

const boundary = {
  type: "FeatureCollection" as const,
  features: [
    {
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [-75.16, 39.95] },
      properties: { police_district: "6" },
    },
    {
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [-75.17, 39.96] },
      properties: { police_district: "9" },
    },
    {
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [-75.18, 39.97] },
      properties: { police_district: "99" },
    },
  ],
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("Philadelphia address search", () => {
  it("uses the bounded legacy lookup and keeps only valid Philadelphia results", async () => {
    const controller = new AbortController();
    const fetcher = vi.fn().mockResolvedValue(
      jsonResponse([
        {
          address: {
            house_number: "1400",
            neighbourhood: "Center City",
            postcode: "19102",
            road: "John F Kennedy Boulevard",
          },
          display_name: "1400 John F Kennedy Boulevard, Philadelphia",
          lat: "39.954",
          lon: "-75.164",
          place_id: 10,
        },
        {
          display_name: "Outside Philadelphia",
          lat: "40.5",
          lon: "-75.1",
          place_id: 11,
        },
        { display_name: "Missing coordinates", place_id: 12 },
      ]),
    );

    const results = await searchPhiladelphiaAddresses("1400 JFK", {
      fetcher,
      signal: controller.signal,
    });

    expect(results).toEqual([
      {
        displayName: "1400 John F Kennedy Boulevard, Philadelphia",
        id: 10,
        lat: 39.954,
        lon: -75.164,
        shortName: "1400 John F Kennedy Boulevard, Center City, 19102",
      },
    ]);
    const [url, init] = fetcher.mock.calls[0];
    const requestUrl = new URL(url);
    expect(requestUrl.origin).toBe("https://nominatim.openstreetmap.org");
    expect(requestUrl.searchParams.get("bounded")).toBe("1");
    expect(requestUrl.searchParams.get("limit")).toBe("5");
    expect(requestUrl.searchParams.get("q")).toBe(
      "1400 JFK, Philadelphia, PA",
    );
    expect(init.signal).toBe(controller.signal);
  });

  it("debounces an accessible combobox and emits its keyboard selection", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-15T12:00:00Z"));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse([
          {
            address: { house_number: "1", road: "S Broad Street" },
            display_name: "1 S Broad Street, Philadelphia, Pennsylvania",
            lat: "39.9501",
            lon: "-75.1642",
            place_id: 20,
          },
        ]),
      ),
    );
    const wrapper = mount(DashboardAddressSearch, { props: { resetKey: 0 } });
    const input = wrapper.get('input[role="combobox"]');

    await input.setValue("Broad Street");
    expect(fetch).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(300);
    await nextTick();

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(wrapper.findAll('[role="option"]')).toHaveLength(1);
    expect(input.attributes("aria-expanded")).toBe("true");
    await input.trigger("keydown", { key: "ArrowDown" });
    await input.trigger("keydown", { key: "Enter" });

    expect(wrapper.emitted("select")?.[0]?.[0]).toEqual(
      expect.objectContaining({ id: 20, lat: 39.9501, lon: -75.1642 }),
    );
    expect((input.element as HTMLInputElement).value).toBe("1 S Broad Street");
    wrapper.unmount();
  });

  it("keeps late results closed after dismissal and outside the tab order", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-15T12:00:00Z"));
    let respond: ((response: Response) => void) | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        () =>
          new Promise<Response>((resolve) => {
            respond = resolve;
          }),
      ),
    );
    const wrapper = mount(DashboardAddressSearch, { props: { resetKey: 0 } });
    const input = wrapper.get('input[role="combobox"]');

    await input.setValue("Broad Street");
    await vi.advanceTimersByTimeAsync(300);
    expect(input.attributes("aria-busy")).toBe("true");

    await input.trigger("keydown", { key: "Escape" });
    respond?.(
      jsonResponse([
        {
          address: { house_number: "1", road: "S Broad Street" },
          display_name: "1 S Broad Street, Philadelphia, Pennsylvania",
          lat: "39.9501",
          lon: "-75.1642",
          place_id: 20,
        },
      ]),
    );
    await flushPromises();

    expect(input.attributes("aria-expanded")).toBe("false");
    expect(wrapper.findAll('[role="option"]')).toHaveLength(0);

    await input.trigger("focus");
    const option = wrapper.get('[role="option"]');
    expect(option.attributes("tabindex")).toBe("-1");
    expect(option.find("svg").exists()).toBe(true);
    expect(wrapper.find('[aria-label="Clear search"] svg').exists()).toBe(true);
    wrapper.unmount();
  });

  it("uses the compact production overlay treatment on top of the map", () => {
    const wrapper = mount(DashboardAddressSearch, {
      props: { resetKey: 0 },
    });
    const input = wrapper.get('input[role="combobox"]');

    expect(wrapper.classes()).toContain(
      "civic-dashboard-address-search--overlay",
    );
    expect(wrapper.find("label").exists()).toBe(false);
    expect(input.attributes("aria-label")).toBe(
      "Search for an address in Philadelphia",
    );
    expect(input.attributes("placeholder")).toBe("Search address...");
    expect(input.attributes("aria-describedby")).toBeUndefined();
  });
});

describe("legacy geographic aggregation", () => {
  it("joins fatal, nonfatal, and total counts without dropping empty areas", () => {
    const rows = [shootingRows[0], { ...shootingRows[0], dc_key: "duplicate" }, shootingRows[1]];
    const joined = joinBoundaryCounts(
      boundary,
      rows as ShootingRow[],
      boundaryOverlayConfig("police-districts"),
    );

    expect(joined.maxCount).toBe(2);
    expect(joined.features.map((feature) => feature.properties)).toEqual([
      expect.objectContaining({ fatal: 2, nonfatal: 0, total_shootings: 2 }),
      expect.objectContaining({ fatal: 0, nonfatal: 1, total_shootings: 1 }),
      expect.objectContaining({ fatal: 0, nonfatal: 0, total_shootings: 0 }),
    ]);
  });

  it("requests only filtered street segments and joins their counts", async () => {
    const fetcher = vi.fn().mockImplementation((input: string) => {
      const url = new URL(input);
      const ids = url.searchParams.get("segment_ids")?.split(",") ?? [];
      return Promise.resolve(
        jsonResponse({
          type: "FeatureCollection",
          features: ids.map((id) => ({
            type: "Feature",
            geometry: { type: "LineString", coordinates: [] },
            properties: { segment_id: id },
          })),
        }),
      );
    });
    const rows = [shootingRows[0], shootingRows[0], shootingRows[1]];

    const joined = await fetchStreetHotSpots(
      "https://api.example.test/base/",
      rows as ShootingRow[],
      { fetcher },
    );

    expect(fetcher).toHaveBeenCalledTimes(1);
    const requestUrl = new URL(fetcher.mock.calls[0][0]);
    expect(requestUrl.pathname).toBe("/base/streets");
    expect(requestUrl.searchParams.get("segment_ids")).toBe(
      "segment-1,segment-2",
    );
    expect(joined.maxCount).toBe(2);
    expect(joined.features[0].properties).toEqual(
      expect.objectContaining({ fatal: 2, nonfatal: 0, total_shootings: 2 }),
    );
  });
});

describe("legacy data downloads", () => {
  it("retains unmapped records while removing internal derived fields", () => {
    const rows = [
      { ...shootingRows[0], street_name: 'MARKET, "EAST"' },
      shootingRows[2],
    ] as ShootingRow[];
    const features = rowsToExportFeatures(rows);

    expect(features).toHaveLength(2);
    expect(features[0].geometry).toEqual({
      type: "Point",
      coordinates: [-75.1602, 39.9526],
    });
    expect(features[1].geometry).toBeNull();
    expect(features[0].properties).not.toHaveProperty("unique_id");
    expect(features[0].properties).not.toHaveProperty("dateInMs");
    expect(features[0].properties).not.toHaveProperty("lat");
    expect(features[0].properties).not.toHaveProperty("lon");
    expect(featuresToCsv(features)).toContain('"MARKET, ""EAST"""');
  });

  it.each(["=", "+", "-", "@", "\t", "\r"])(
    "refuses a spreadsheet-formula prefix %s in a CSV cell",
    (prefix) => {
      const features = rowsToExportFeatures([
        { ...shootingRows[0], street_name: `${prefix}unsafe` },
      ] as ShootingRow[]);

      expect(() => featuresToCsv(features)).toThrow(
        /spreadsheet software could treat as a formula/i,
      );
    },
  );

  it("creates the same fatal/nonfatal aggregation for CSV and GeoJSON", async () => {
    const rows = [shootingRows[0], shootingRows[1], shootingRows[3]] as ShootingRow[];
    expect(aggregateShootingRows(rows, "police-districts")).toEqual([
      { police_district: "6", total_shootings: 1, fatal: 1, nonfatal: 0 },
      { police_district: "9", total_shootings: 1, fatal: 0, nonfatal: 1 },
      { police_district: "25", total_shootings: 1, fatal: 0, nonfatal: 1 },
    ]);

    const fetcher = vi.fn().mockResolvedValue(jsonResponse(boundary));
    const file = await createShootingDownload(
      "https://api.example.test",
      rows,
      shootingRows as ShootingRow[],
      {
        aggregateBy: "police-districts",
        format: "geojson",
        useFiltered: true,
      },
      { fetcher, today: "2026-08-15" },
    );

    expect(fetcher).toHaveBeenCalledWith(
      "https://api.example.test/boundaries/police_districts",
      expect.any(Object),
    );
    expect(file.filename).toBe(
      "shootings-by-police-districts-filtered-2026-08-15.geojson",
    );
    const collection = JSON.parse(file.content);
    expect(collection.features).toHaveLength(3);
    expect(collection.features[2].properties.total_shootings).toBe(0);
  });

  it("downloads from a native modal with filtered GeoJSON defaults", async () => {
    const createObjectURL = vi.fn(() => "blob:test-download");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL }));
    let downloadedAs = "";
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      function (this: HTMLAnchorElement) {
        downloadedAs = this.download;
      },
    );
    const wrapper = mount(DashboardDownloadPanel, {
      props: {
        allRows: shootingRows as ShootingRow[],
        apiBaseUrl: "https://api.example.test",
        filteredRows: shootingRows.slice(0, 2) as ShootingRow[],
      },
      global: { components: { CivicIcon } },
    });

    const trigger = wrapper.get(".civic-dashboard-download__trigger");
    const dialog = wrapper.get("#dashboard-download-dialog");
    const heading = wrapper.get("#dashboard-download-title");
    const submit = wrapper.get(".civic-dashboard-download__submit");
    expect(trigger.text()).toBe("Download Data");
    expect(trigger.attributes("aria-haspopup")).toBe("dialog");
    expect(trigger.attributes("aria-controls")).toBe(
      "dashboard-download-dialog",
    );
    expect(trigger.get("svg").attributes("aria-hidden")).toBe("true");
    expect(dialog.element.tagName).toBe("DIALOG");
    expect(dialog.attributes("aria-labelledby")).toBe(
      "dashboard-download-title",
    );
    expect(heading.text()).toBe("Download Data");
    expect(heading.find("svg").exists()).toBe(false);
    expect(dialog.attributes("open")).toBeUndefined();
    expect(
      (wrapper.get("#dashboard-download-filtered").element as HTMLInputElement)
        .checked,
    ).toBe(true);
    expect(
      (wrapper.get("#dashboard-download-geojson").element as HTMLInputElement)
        .checked,
    ).toBe(true);
    expect(
      wrapper.findAll(".civic-dashboard-download__group"),
    ).toHaveLength(3);
    expect(
      wrapper
        .findAll(".civic-dashboard-download__option")
        .map((option) => option.text()),
    ).toEqual(["Filtered Data", "All Data", "CSV", "GeoJSON"]);
    expect(submit.text()).toBe("Download GeoJSON");
    expect(submit.get("svg").attributes("aria-hidden")).toBe("true");
    expect(wrapper.get("#dashboard-download-format-description").text()).toBe(
      "Geographic format with coordinates",
    );

    await trigger.trigger("click");
    expect(dialog.attributes("open")).toBeDefined();
    expect(wrapper.text()).toContain(
      "Export 2 records matching current filters",
    );
    await wrapper.get("#dashboard-download-all").setValue(true);
    expect(wrapper.text()).toContain("Export all 4 records");
    await wrapper.get("#dashboard-download-filtered").setValue(true);
    await wrapper.get("#dashboard-download-csv").setValue(true);
    expect(submit.text()).toBe("Download CSV");
    expect(wrapper.get("#dashboard-download-format-description").text()).toBe(
      "A table with latitude and longitude columns.",
    );
    await wrapper.get("form").trigger("submit");
    await vi.waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));

    expect(downloadedAs).toMatch(/^shootings-filtered-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:test-download");
    expect(dialog.attributes("open")).toBeUndefined();
  });

  it("freezes choices but keeps cancellation available while preparing a download", async () => {
    let releaseFetch!: (response: Response) => void;
    const pendingFetch = new Promise<Response>((resolve) => {
      releaseFetch = resolve;
    });
    vi.stubGlobal("fetch", vi.fn(() => pendingFetch));

    const createObjectURL = vi.fn(() => "blob:pending-download");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    const wrapper = mount(DashboardDownloadPanel, {
      props: {
        allRows: shootingRows as ShootingRow[],
        apiBaseUrl: "https://api.example.test",
        filteredRows: shootingRows.slice(0, 2) as ShootingRow[],
      },
      global: { components: { CivicIcon } },
    });
    const dialog = wrapper.get("#dashboard-download-dialog");

    await wrapper.get(".civic-dashboard-download__trigger").trigger("click");
    await wrapper.get("#dashboard-download-all").setValue(true);
    await wrapper.get("#dashboard-download-aggregate").setValue("police-districts");
    await wrapper.get("form").trigger("submit");

    expect(dialog.attributes("aria-busy")).toBe("true");
    expect(wrapper.get(".civic-dashboard-download__submit").text()).toBe(
      "Preparing GeoJSON…",
    );
    expect(
      dialog
        .findAll("input, select, .civic-dashboard-download__submit")
        .every((control) => control.attributes("disabled") !== undefined),
    ).toBe(true);
    expect(
      wrapper.get(".civic-dashboard-download__cancel").attributes("disabled"),
    ).toBeUndefined();
    expect(
      (wrapper.get("#dashboard-download-all").element as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (wrapper.get("#dashboard-download-geojson").element as HTMLInputElement)
        .checked,
    ).toBe(true);
    expect(
      (wrapper.get("#dashboard-download-aggregate").element as HTMLSelectElement)
        .value,
    ).toBe("police-districts");

    releaseFetch(jsonResponse(boundary));
    await flushPromises();

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:pending-download");
    expect(dialog.attributes("open")).toBeUndefined();
  });

  it("aborts cancellation and ignores a late download response", async () => {
    let releaseFetch!: (response: Response) => void;
    let requestSignal: AbortSignal | undefined;
    const pendingFetch = new Promise<Response>((resolve) => {
      releaseFetch = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn((_input: string, init?: RequestInit) => {
        requestSignal = init?.signal ?? undefined;
        return pendingFetch;
      }),
    );
    const createObjectURL = vi.fn(() => "blob:late-download");
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL,
        revokeObjectURL: vi.fn(),
      }),
    );
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    const wrapper = mount(DashboardDownloadPanel, {
      props: {
        allRows: shootingRows as ShootingRow[],
        apiBaseUrl: "https://api.example.test",
        filteredRows: shootingRows as ShootingRow[],
      },
      global: { components: { CivicIcon } },
    });
    const dialog = wrapper.get("#dashboard-download-dialog");

    await wrapper.get(".civic-dashboard-download__trigger").trigger("click");
    await wrapper
      .get("#dashboard-download-aggregate")
      .setValue("police-districts");
    await wrapper.get("form").trigger("submit");
    expect(requestSignal?.aborted).toBe(false);

    await wrapper.get(".civic-dashboard-download__cancel").trigger("click");
    expect(requestSignal?.aborted).toBe(true);
    expect(dialog.attributes("open")).toBeUndefined();

    releaseFetch(jsonResponse(boundary));
    await flushPromises();
    expect(createObjectURL).not.toHaveBeenCalled();
  });

  it("aborts preparation on navigation and cannot download after unmount", async () => {
    let releaseFetch!: (response: Response) => void;
    let requestSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((_input: string, init?: RequestInit) => {
        requestSignal = init?.signal ?? undefined;
        return new Promise<Response>((resolve) => {
          releaseFetch = resolve;
        });
      }),
    );
    const createObjectURL = vi.fn(() => "blob:unmounted-download");
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL,
        revokeObjectURL: vi.fn(),
      }),
    );
    const wrapper = mount(DashboardDownloadPanel, {
      props: {
        allRows: shootingRows as ShootingRow[],
        apiBaseUrl: "https://api.example.test",
        filteredRows: shootingRows as ShootingRow[],
      },
      global: { components: { CivicIcon } },
    });

    await wrapper.get(".civic-dashboard-download__trigger").trigger("click");
    await wrapper
      .get("#dashboard-download-aggregate")
      .setValue("police-districts");
    await wrapper.get("form").trigger("submit");
    wrapper.unmount();
    expect(requestSignal?.aborted).toBe(true);

    releaseFetch(jsonResponse(boundary));
    await flushPromises();
    expect(createObjectURL).not.toHaveBeenCalled();
  });

  it("bounds a stalled preparation and reports its timeout", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn((_input: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        }),
      ),
    );
    const wrapper = mount(DashboardDownloadPanel, {
      props: {
        allRows: shootingRows as ShootingRow[],
        apiBaseUrl: "https://api.example.test",
        filteredRows: shootingRows as ShootingRow[],
      },
      global: { components: { CivicIcon } },
    });

    await wrapper.get(".civic-dashboard-download__trigger").trigger("click");
    await wrapper
      .get("#dashboard-download-aggregate")
      .setValue("police-districts");
    await wrapper.get("form").trigger("submit");
    await vi.advanceTimersByTimeAsync(15_000);
    await flushPromises();

    expect(wrapper.get('[role="alert"]').text()).toBe(
      "The download took too long to prepare. Try again.",
    );
    expect(
      wrapper.get(".civic-dashboard-download__submit").attributes("disabled"),
    ).toBeUndefined();
  });
});

describe("synchronized category charts", () => {
  it("keeps inconclusive court searches in an explicit Unknown category", () => {
    const rows = [shootingRows[0], shootingRows[1], shootingRows[3]];
    const wrapper = mount(DashboardCategoryCharts, {
      props: { rows: rows as ShootingRow[] },
    });
    const courtChart = wrapper.get(
      ".civic-dashboard-category-chart--court",
    );

    expect(
      courtChart
        .get('table[aria-label="Court Search Result distribution breakdown"]')
        .findAll("tbody tr")
        .map((row) =>
          row
            .findAll("td")
            .slice(0, 2)
            .map((cell) => cell.text()),
        ),
    ).toEqual([
      ["Yes", "1"],
      ["No", "1"],
      ["Unknown", "1"],
    ]);
    expect(courtChart.get(".civic-info-tooltip__panel").text()).toContain(
      "explicit no-results response",
    );
    expect(courtChart.get(".civic-info-tooltip__panel").text()).toContain(
      "unavailable, incomplete, or inconclusive",
    );
    expect(courtChart.get(".civic-info-tooltip__panel").text()).toContain(
      "does not establish how a record relates to a victim",
    );
  });

  it("adds complete full-run coverage to the existing court tooltip", () => {
    const wrapper = mount(DashboardCategoryCharts, {
      props: {
        courtCoverageNote:
          "The last published full run was processed August 20, 2026, with terminal results accounting for all 15,753 eligible incident numbers.",
        rows: shootingRows as ShootingRow[],
      },
    });

    const tooltip = wrapper
      .get(".civic-dashboard-category-chart--court")
      .get(".civic-info-tooltip__panel")
      .text();
    expect(tooltip).toContain("last published full run");
    expect(tooltip).toContain("15,753 eligible incident numbers");
  });

  it("renders precomputed counts before detailed browser records load", () => {
    const wrapper = mount(DashboardCategoryCharts, {
      props: {
        rows: [],
        state: "loading",
        summary: {
          year: 2026,
          total: 3,
          outcome: { true: 1, false: 2 },
          court: { true: 1, false: 0, null: 2 },
          gender: { M: 2, F: 1 },
          race: { W: 0, B: 2, H: 1, A: 0, "Other/Unknown": 0 },
          age: {
            "Younger than 18": 0,
            "18 to 30": 2,
            "31 to 45": 0,
            "Older than 45": 1,
            Unknown: 0,
          },
        },
      },
    });

    expect(wrapper.findAll("figure")).toHaveLength(5);
    expect(
      wrapper
        .get('table[aria-label="Court Search Result distribution breakdown"]')
        .findAll("tbody tr")
        .map((row) => row.findAll("td").map((cell) => cell.text())),
    ).toEqual([
      ["Yes", "1", "33.3%"],
      ["No", "0", "0%"],
      ["Unknown", "2", "66.7%"],
    ]);
    expect(wrapper.find('[role="status"]').exists()).toBe(false);
  });

  it("renders the five legacy breakdowns and updates from filtered rows", async () => {
    const wrapper = mount(DashboardCategoryCharts, {
      props: { rows: shootingRows as ShootingRow[] },
    });

    expect(wrapper.findAll("figure")).toHaveLength(5);
    expect(wrapper.findAll("figcaption").map((item) => item.text())).toEqual([
      expect.stringContaining("Outcome"),
      expect.stringContaining("Court Search Result"),
      expect.stringContaining("Gender"),
      expect.stringContaining("Race/Ethnicity"),
      expect.stringContaining("Age Group"),
    ]);
    const definitionControls = wrapper.findAll(
      "[data-chart-definition] .civic-info-tooltip__trigger",
    );
    expect(definitionControls).toHaveLength(5);
    expect(definitionControls.map((item) => item.text())).toEqual(
      expect.arrayContaining([
        expect.stringContaining("About Outcome"),
        expect.stringContaining("About Court Search Result"),
        expect.stringContaining("About Gender"),
        expect.stringContaining("About Race/Ethnicity"),
        expect.stringContaining("About Age Group"),
      ]),
    );
    const definitions = wrapper.findAll(".civic-info-tooltip__panel");
    expect(definitions).toHaveLength(5);
    expect(
      definitionControls.every(
        (item, index) =>
          item.attributes("aria-controls") ===
            definitions[index]?.attributes("id") &&
          item.attributes("aria-expanded") === "false" &&
          item.attributes("aria-haspopup") === "dialog" &&
          item.attributes("aria-describedby") ===
            definitions[index]?.attributes("id"),
      ),
    ).toBe(true);
    expect(
      definitions.every(
        (definition) =>
          definition.attributes("role") === "tooltip" &&
          definition.attributes("aria-label") === undefined,
      ),
    ).toBe(true);
    expect(
      definitions.every(
        (definition) =>
          (definition.element as HTMLElement).style.display === "none",
      ),
    ).toBe(true);
    const definitionCopy = definitions.map((definition) => definition.text());
    expect(definitionCopy).toEqual(
      expect.arrayContaining([
        expect.stringContaining("classified as fatal"),
        expect.stringContaining("explicit no-results response"),
        expect.stringContaining("reported sex field"),
        expect.stringContaining("Latino indicator"),
        expect.stringContaining("derived from reported age"),
      ]),
    );
    const charts = wrapper.get("section");
    expect(charts.attributes("role")).toBe("region");
    expect(charts.attributes("tabindex")).toBe("-1");
    expect(charts.get("h2.usa-sr-only").text()).toBe(
      "Shooting Victim Statistics by Category",
    );
    expect(wrapper.text()).not.toContain("same 4 records");
    expect(
      wrapper
        .get('table[aria-label="Outcome distribution breakdown"] tbody tr')
        .findAll("td")
        .map((cell) => cell.text()),
    ).toEqual(["Fatal", "2", "50%"]);

    await wrapper.setProps({ rows: shootingRows.slice(0, 1) as ShootingRow[] });
    await nextTick();
    expect(wrapper.text()).not.toContain("same 1 record");
    expect(
      wrapper
        .get('table[aria-label="Outcome distribution breakdown"] tbody tr')
        .findAll("td")
        .map((cell) => cell.text()),
    ).toEqual(["Fatal", "1", "100%"]);
    expect(
      wrapper
        .get('table[aria-label="Gender distribution breakdown"] tbody tr')
        .findAll("td")
        .map((cell) => cell.text()),
    ).toEqual(["Male", "1", "100%"]);
  });

  it("shows an anchored definition on hover, focus, and touch-style clicks", async () => {
    const wrapper = mount(DashboardCategoryCharts, {
      props: { rows: shootingRows as ShootingRow[] },
      attachTo: document.body,
    });
    const definition = wrapper.get(
      '.civic-dashboard-category-chart--outcome [data-chart-definition]',
    );
    const trigger = definition.get(".civic-info-tooltip__trigger");
    const tooltip = definition.get(".civic-info-tooltip__panel");
    const isVisible = () =>
      (tooltip.element as HTMLElement).style.display !== "none";

    expect(isVisible()).toBe(false);
    expect(definition.classes()).not.toContain("civic-info-tooltip--open");

    await definition.trigger("pointerenter");
    expect(isVisible()).toBe(true);
    expect(tooltip.attributes("role")).toBe("tooltip");
    expect(definition.classes()).toContain("civic-info-tooltip--open");
    await definition.trigger("pointerleave");
    expect(isVisible()).toBe(false);

    await trigger.trigger("click");
    expect(isVisible()).toBe(true);
    expect(tooltip.attributes("role")).toBe("dialog");
    expect(tooltip.attributes("aria-label")).toBe("Outcome information");
    expect(
      definition.find('button[aria-label="Close Outcome information"]').exists(),
    ).toBe(true);
    await trigger.trigger("focusout");
    expect(isVisible()).toBe(false);

    (trigger.element as HTMLButtonElement).focus();
    await nextTick();
    expect(isVisible()).toBe(true);
    await trigger.trigger("keydown", { key: "Escape" });
    expect(isVisible()).toBe(false);
    expect(document.activeElement).toBe(trigger.element);

    await wrapper.setProps({ rows: [] });
    await wrapper.setProps({ rows: shootingRows as ShootingRow[] });
    expect(
      wrapper
        .get(
          '.civic-dashboard-category-chart--outcome [data-chart-definition]',
        )
        .classes(),
    ).not.toContain("civic-info-tooltip--open");

    wrapper.unmount();
  });

  it("keeps exact one-decimal shares without changing counts or bar scale", () => {
    const rows = Array.from({ length: 8 }, (_, index) => ({
      ...shootingRows[index % shootingRows.length],
      dc_key: `percentage-${index}`,
      fatal: index === 0,
      unique_id: 100 + index,
    })) as ShootingRow[];
    const wrapper = mount(DashboardCategoryCharts, { props: { rows } });
    const outcome = wrapper.get(".civic-dashboard-category-chart--outcome");
    const tableValues = outcome
      .findAll("tbody tr")
      .map((row) => row.findAll("td").map((cell) => cell.text()));
    const displayedPercentages = outcome
      .findAll(".civic-dashboard-category-chart__percent")
      .map((item) => Number(item.text().replace(/[()%\s]/g, "")));
    const tablePercentages = tableValues.map(([, , percent]) =>
      Number(percent?.replace("%", "")),
    );
    const barWidths = outcome
      .findAll<HTMLElement>(".civic-dashboard-category-chart__track")
      .map((track) =>
        Number.parseFloat(
          track.element.style.getPropertyValue("--chart-bar-width"),
        ),
      );

    expect(tableValues).toEqual([
      ["Fatal", "1", "12.5%"],
      ["Nonfatal", "7", "87.5%"],
    ]);
    expect(displayedPercentages).toEqual(tablePercentages);
    expect(tablePercentages.reduce((total, percent) => total + percent, 0)).toBe(
      100,
    );
    expect(barWidths[0]).toBeCloseTo((1 / 7) * 100, 5);
    expect(barWidths[1]).toBeCloseTo(100, 5);
  });

  it("balances rounding so displayed category shares total exactly 100", () => {
    const rows = Array.from({ length: 16 }, (_, index) => ({
      ...shootingRows[index % shootingRows.length],
      dc_key: `rounding-${index}`,
      fatal: index === 0,
      unique_id: 200 + index,
    })) as ShootingRow[];
    const wrapper = mount(DashboardCategoryCharts, { props: { rows } });
    const percentages = wrapper
      .get(".civic-dashboard-category-chart--outcome")
      .findAll("tbody tr")
      .map((row) => row.findAll("td").at(-1)?.text());

    expect(percentages).toEqual(["6.3%", "93.7%"]);
    expect(
      percentages.reduce(
        (total, percent) => total + Number.parseFloat(percent ?? "0"),
        0,
      ),
    ).toBe(100);
    expect(
      wrapper.find(".civic-dashboard-category-charts__rounding-note").exists(),
    ).toBe(false);
  });

  it("keeps the charts skip target available when no records match", () => {
    const wrapper = mount(DashboardCategoryCharts, { props: { rows: [] } });

    expect(wrapper.get("#charts").attributes("tabindex")).toBe("-1");
    expect(wrapper.get('[role="status"]').text()).toBe(
      "No shooting-victim records match the current filters.",
    );
    expect(wrapper.findAll("figure")).toHaveLength(0);
  });
});
