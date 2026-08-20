import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, nextTick } from "vue";

import DashboardCheckboxFilter from "../../../app/components/DashboardCheckboxFilter.vue";
import DashboardExplorer from "../../../app/components/DashboardExplorer.client.vue";
import DashboardRangeFilter from "../../../app/components/DashboardRangeFilter.vue";
import {
  DEFAULT_MAP_LAYERS,
  type MapLayerId,
} from "../../../app/utils/mapLayers";
import { DEFAULT_MAP_VIEW } from "../../../app/utils/mapView";
import {
  rowsNdjson,
  shootingRows,
  shootingsMeta,
} from "../../fixtures/shootings";

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

const PointMapStub = defineComponent({
  name: "DashboardPointMap",
  props: {
    fatalOnly: { type: Boolean, required: true },
    layers: { type: Array, required: true },
    records: { type: Object, required: true },
    year: { required: true },
  },
  template:
    '<div data-test="point-map">{{ records.recordCount }} filtered map records; fatal only: {{ fatalOnly }}; {{ year === null ? "all years" : year }}</div>',
});

const routerReplace = vi.fn();

describe("DashboardCheckboxFilter", () => {
  it("supports individual choices, only, and reset with native controls", async () => {
    const wrapper = mount(DashboardCheckboxFilter, {
      props: {
        defaultValues: ["M", "F"],
        id: "gender-test",
        items: [
          { label: "Male", value: "M" },
          { label: "Female", value: "F" },
        ],
        label: "Gender",
        selectedValues: ["M"],
      },
    });

    expect(wrapper.get("legend").text()).toBe("Gender");
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(2);
    expect(
      (wrapper.get("#gender-test-0").element as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (wrapper.get("#gender-test-1").element as HTMLInputElement).checked,
    ).toBe(false);

    await wrapper.get("#gender-test-1").setValue(true);
    expect(wrapper.emitted("update:selectedValues")?.at(-1)).toEqual([
      ["M", "F"],
    ]);
    await wrapper
      .get('button[aria-label="Select only Female for Gender"]')
      .trigger("click");
    expect(wrapper.emitted("select-only")?.at(-1)).toEqual(["F"]);
    await wrapper.get(".civic-dashboard-filter-reset").trigger("click");
    expect(wrapper.emitted("reset")).toHaveLength(1);
  });

  it("can omit the contextual reset without changing checkbox behavior", async () => {
    const wrapper = mount(DashboardCheckboxFilter, {
      props: {
        defaultValues: ["points"],
        id: "layer-test",
        items: [
          { label: "Points", value: "points" },
          { label: "Heat map", value: "heat" },
        ],
        label: "Map layers",
        resettable: false,
        selectedValues: ["heat"],
      },
    });

    expect(wrapper.find(".civic-dashboard-filter-reset").exists()).toBe(false);
    await wrapper.get("#layer-test-0").setValue(true);
    expect(wrapper.emitted("update:selectedValues")?.at(-1)).toEqual([
      ["points", "heat"],
    ]);
  });
});

describe("DashboardRangeFilter", () => {
  it("exposes both range bounds, the histogram, missing-value choice, and reset", async () => {
    const wrapper = mount(DashboardRangeFilter, {
      props: {
        bins: [
          { length: 1, x0: 0, x1: 10 },
          { length: 3, x0: 10, x1: 20 },
        ],
        defaultRange: [0, 100],
        excludeMissing: true,
        format: "age",
        id: "age-test",
        label: "Age",
        range: [10, 80],
        showExcludeMissing: true,
        step: 1,
      },
    });

    expect(wrapper.get("legend").text()).toBe("Age");
    expect(wrapper.get('[role="img"]').attributes("aria-label")).toContain(
      "Age distribution",
    );
    expect(
      wrapper.findAll(
        ".civic-dashboard-range-filter__histogram > span:not(.civic-dashboard-range-filter__limit)",
      ),
    ).toHaveLength(2);
    expect(
      wrapper.findAll(".civic-dashboard-range-filter__limit"),
    ).toHaveLength(2);
    expect(
      wrapper
        .findAll(".civic-dashboard-range-filter__limit")
        .map((limit) => limit.attributes("style")),
    ).toEqual([
      "left: calc(10% + 0.2rem);",
      "left: calc(80% - 0.15rem);",
    ]);
    expect(
      wrapper
        .findAll(".civic-dashboard-range-filter__thumb-label")
        .map((label) => label.text()),
    ).toEqual(["10", "80"]);
    expect(
      (wrapper.get('input[type="checkbox"]').element as HTMLInputElement)
        .checked,
    ).toBe(true);

    await wrapper.get("#age-test-lower").setValue(25);
    expect(wrapper.emitted("update:range")?.at(-1)).toEqual([[25, 80]]);
    await wrapper.get('input[type="checkbox"]').setValue(false);
    expect(wrapper.emitted("update:excludeMissing")?.at(-1)).toEqual([false]);
    await wrapper.get(".civic-dashboard-range-filter__reset").trigger("click");
    expect(wrapper.emitted("reset")).toHaveLength(1);
  });

  it("includes years for All Years dates while keeping single-year dates compact", () => {
    const allYearsRange: [number, number] = [
      Date.UTC(2020, 0, 1),
      Date.UTC(2026, 11, 31),
    ];
    const allYears = mount(DashboardRangeFilter, {
      props: {
        bins: [],
        defaultRange: allYearsRange,
        format: "date",
        id: "all-years-date-test",
        includeYear: true,
        label: "Date",
        range: allYearsRange,
        step: 86_400_000,
      },
    });

    expect(
      allYears
        .findAll(".civic-dashboard-range-filter__thumb-label")
        .map((label) => label.text()),
    ).toEqual(["Jan 1, 2020", "Dec 31, 2026"]);
    expect(
      allYears
        .findAll(".civic-dashboard-range-filter__thumb-label")
        .map((label) => label.attributes("style")),
    ).toEqual([
      "--range-position: 0%;",
      "--range-position: 100%;",
    ]);
    expect(
      allYears.get("#all-years-date-test-lower").attributes("aria-valuetext"),
    ).toBe("Jan 1, 2020");
    expect(
      allYears.get("#all-years-date-test-upper").attributes("aria-valuetext"),
    ).toBe("Dec 31, 2026");

    const selectedYearRange: [number, number] = [
      Date.UTC(2026, 1, 1),
      Date.UTC(2026, 10, 30),
    ];
    const selectedYear = mount(DashboardRangeFilter, {
      props: {
        bins: [],
        defaultRange: [Date.UTC(2026, 0, 1), Date.UTC(2026, 11, 31)],
        format: "date",
        id: "selected-year-date-test",
        label: "Date",
        range: selectedYearRange,
        step: 86_400_000,
      },
    });

    expect(
      selectedYear
        .findAll(".civic-dashboard-range-filter__thumb-label")
        .map((label) => label.text()),
    ).toEqual(["Feb 1", "Nov 30"]);
    expect(
      selectedYear
        .get("#selected-year-date-test-lower")
        .attributes("aria-valuetext"),
    ).toBe("Feb 1");
    expect(
      selectedYear
        .get("#selected-year-date-test-upper")
        .attributes("aria-valuetext"),
    ).toBe("Nov 30");
  });
});

describe("DashboardExplorer", () => {
  beforeEach(() => {
    vi.stubGlobal("useRoute", () => ({ query: {} }));
    routerReplace.mockReset();
    vi.stubGlobal("useRouter", () => ({ replace: routerReplace }));
    vi.stubGlobal("useRuntimeConfig", () => ({
      public: { apiBaseUrl: "https://api.example.test" },
    }));
    vi.stubGlobal("useDatasetMeta", () => ({ data: { value: null } }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function mountExplorer(
    year: number | null = 2026,
    layers: MapLayerId[] = [...DEFAULT_MAP_LAYERS],
  ) {
    return mount(DashboardExplorer, {
      props: {
        initialView: DEFAULT_MAP_VIEW,
        layers,
        year,
      },
      global: {
        stubs: { DashboardPointMap: PointMapStub },
      },
    });
  }

  it("renders the production map/sidebar structure and shares filters with its summaries", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(shootingsMeta))
      .mockResolvedValueOnce(textResponse(rowsNdjson));
    vi.stubGlobal("fetch", fetcher);
    const wrapper = mountExplorer();

    expect(wrapper.text()).toContain("Loading 2026 record filters and locations");
    await vi.waitFor(() =>
      expect(wrapper.get(".civic-legacy-sidebar__count").text()).toContain(
        "3 shooting victims",
      ),
    );

    expect(fetcher).toHaveBeenCalledTimes(2);
    const explorer = wrapper.get(".civic-legacy-map-explorer");
    expect(explorer.element.children[0]?.classList).toContain(
      "civic-legacy-map-view",
    );
    expect(explorer.element.children[1]?.classList).toContain(
      "civic-legacy-sidebar",
    );
    expect(wrapper.get("aside").attributes("aria-label")).toBe(
      "Map filters and controls",
    );

    const filterPanels = wrapper.findAll("details.civic-disclosure-panel");
    expect(filterPanels).toHaveLength(6);
    expect(filterPanels.map((item) => item.get("summary").text())).toEqual([
      "Gender",
      "Race/Ethnicity",
      "Day of Week",
      "Time of Day",
      "Date",
      "Age",
    ]);
    expect(
      filterPanels.every(
        (item) => !(item.element as HTMLDetailsElement).open,
      ),
    ).toBe(true);
    expect(wrapper.findAll(".civic-legacy-switches input")).toHaveLength(2);
    expect(wrapper.get('[data-test="point-map"]').text()).toContain(
      "4 filtered map records",
    );
    expect(wrapper.findAll("figure")).toHaveLength(5);
    const charts = wrapper.get(".civic-dashboard-category-charts");
    expect(charts.attributes("role")).toBe("region");
    expect(charts.attributes("tabindex")).toBe("-1");
    expect(charts.get("h2.usa-sr-only").text()).toBe(
      "Shooting Victim Statistics by Category",
    );
    expect(wrapper.text()).not.toContain("same 4 records");
    expect(
      wrapper.get(".civic-dashboard-download__trigger").attributes(
        "aria-haspopup",
      ),
    ).toBe("dialog");
    expect(wrapper.get("#dashboard-download-dialog").element.tagName).toBe(
      "DIALOG",
    );
    expect(wrapper.get('input[role="combobox"]').attributes("aria-label")).toBe(
      "Search for an address in Philadelphia",
    );
    expect(wrapper.get('input[role="combobox"]').attributes("placeholder")).toBe(
      "Search address...",
    );
    expect(wrapper.emitted("summary")?.at(-1)).toEqual([
      { fatal: 2, mapped: 3, nonfatal: 2, total: 4 },
    ]);
    expect(
      wrapper.get(".civic-legacy-sidebar__note").classes(),
    ).not.toContain("civic-legacy-sidebar__note--empty");
    expect(
      wrapper.get(".civic-legacy-sidebar__note").attributes("aria-hidden"),
    ).toBeUndefined();

    const mapLayers = wrapper
      .findAll("fieldset")
      .find((item) => item.get("legend").text() === "Map layers");
    expect(mapLayers).toBeDefined();
    await mapLayers!.get("#dashboard-map-layer-0").setValue(false);
    expect(routerReplace).toHaveBeenLastCalledWith({ query: { layers: "" } });
    expect(
      mapLayers!.find('button[aria-label="Reset Map layers filter"]').exists(),
    ).toBe(false);
    await wrapper.get("#dashboard-boundary-layer").setValue("zip-codes");
    expect(routerReplace).toHaveBeenLastCalledWith({
      query: { layers: "zip-codes" },
    });

    await wrapper.get("#dashboard-fatal-filter").setValue(true);
    await nextTick();
    expect(wrapper.emitted("summary")?.at(-1)).toEqual([
      { fatal: 2, mapped: 1, nonfatal: 0, total: 2 },
    ]);
    expect(wrapper.get('[data-test="point-map"]').text()).toContain(
      "fatal only: true",
    );
    await wrapper.get("#dashboard-fatal-filter").setValue(false);

    await wrapper.get("#dashboard-court-filter").setValue(true);
    await nextTick();
    expect(wrapper.emitted("summary")?.at(-1)?.[0]).toMatchObject({
      mapped: 1,
      total: 2,
    });
    await wrapper.get("#dashboard-court-filter").setValue(false);

    const genderFilter = wrapper
      .findAll("fieldset")
      .find((item) => item.get("legend").text() === "Gender");
    expect(genderFilter).toBeDefined();
    await genderFilter!
      .get('button[aria-label="Select only Female for Gender"]')
      .trigger("click");
    await nextTick();
    expect(wrapper.emitted("summary")?.at(-1)).toEqual([
      { fatal: 0, mapped: 1, nonfatal: 1, total: 1 },
    ]);
    expect(wrapper.get(".civic-legacy-sidebar__note").classes()).toContain(
      "civic-legacy-sidebar__note--empty",
    );
    expect(
      wrapper.get(".civic-legacy-sidebar__note").attributes("aria-hidden"),
    ).toBe("true");
    const genderReset = wrapper.get(
      'button[aria-label="Reset Gender filter"]',
    );
    expect(genderReset.element.closest("details")).toBeNull();
    await genderReset.trigger("click");

    const ageFilter = wrapper
      .findAll("fieldset")
      .find((item) => item.get("legend").text() === "Age");
    expect(ageFilter).toBeDefined();
    await ageFilter!.get('input[type="range"]').setValue(30);
    await nextTick();
    expect(wrapper.emitted("summary")?.at(-1)?.[0]).toMatchObject({
      mapped: 2,
      total: 3,
    });
    expect(wrapper.get('[data-test="point-map"]').text()).toContain(
      "3 filtered map records",
    );

    await ageFilter!.get('input[type="checkbox"]').setValue(true);
    await nextTick();
    expect(wrapper.emitted("summary")?.at(-1)?.[0]).toMatchObject({
      mapped: 1,
      total: 2,
    });

    const ageReset = wrapper.get('button[aria-label="Reset Age filter"]');
    expect(ageReset.element.closest("details")).toBeNull();
    await ageReset.trigger("click");
    await nextTick();
    expect(wrapper.emitted("summary")?.at(-1)?.[0]).toMatchObject({
      mapped: 3,
      total: 4,
    });

    await wrapper.get("#dashboard-fatal-filter").setValue(true);
    await nextTick();
    const resetAll = wrapper
      .findAll("button")
      .find((button) => button.text() === "Reset All Filters");
    expect(resetAll).toBeDefined();
    await resetAll!.trigger("click");
    await nextTick();
    expect(wrapper.emitted("summary")?.at(-1)?.[0]).toMatchObject({
      mapped: 3,
      total: 4,
    });
    expect(fetcher).toHaveBeenCalledTimes(2);

    wrapper.unmount();
  });

  it("restores toggleable layers after switching between choropleths and clearing", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(shootingsMeta))
      .mockResolvedValueOnce(textResponse(rowsNdjson));
    vi.stubGlobal("fetch", fetcher);
    const wrapper = mountExplorer(2026, ["point-locations", "heat-map"]);

    await vi.waitFor(() =>
      expect(wrapper.find("#dashboard-boundary-layer").exists()).toBe(true),
    );

    const boundarySelect = wrapper.get("#dashboard-boundary-layer");
    expect(
      wrapper.get('label[for="dashboard-boundary-layer"]').text(),
    ).toBe("Choropleth Layer");
    expect(
      boundarySelect
        .findAll("option:not([hidden])")
        .map((option) => option.text()),
    ).toEqual([
      "Police Districts",
      "Council Districts",
      "ZIP Codes",
      "Neighborhoods",
      "PA House Districts",
      "PA Senate Districts",
      "School Catchments",
    ]);

    await boundarySelect.setValue("police-districts");
    expect(routerReplace).toHaveBeenLastCalledWith({
      query: { layers: "police-districts" },
    });
    await wrapper.setProps({ layers: ["police-districts"] });

    await boundarySelect.setValue("zip-codes");
    expect(routerReplace).toHaveBeenLastCalledWith({
      query: { layers: "zip-codes" },
    });
    await wrapper.setProps({ layers: ["zip-codes"] });

    await wrapper
      .get('button[aria-label="Clear Choropleth Layer"]')
      .trigger("click");
    expect(routerReplace).toHaveBeenLastCalledWith({
      query: { layers: "point-locations,heat-map" },
    });
    wrapper.unmount();
  });

  it.each([
    ["Point locations", "point-locations", undefined],
    ["Heat map", "heat-map", "heat-map"],
    [
      "Hot spots by street block",
      "hot-spots-by-street-block",
      "hot-spots-by-street-block",
    ],
  ] as const)(
    "switches directly from a choropleth to only %s",
    async (label, layer, queryValue) => {
      const fetcher = vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(shootingsMeta))
        .mockResolvedValueOnce(textResponse(rowsNdjson));
      vi.stubGlobal("fetch", fetcher);
      const wrapper = mountExplorer(2026, ["zip-codes"]);

      await vi.waitFor(() =>
        expect(wrapper.find("#dashboard-boundary-layer").exists()).toBe(true),
      );

      const checkboxes = wrapper.findAll(
        'fieldset:has(legend) input[id^="dashboard-map-layer-"]',
      );
      expect(checkboxes).toHaveLength(3);
      expect(
        checkboxes.every(
          (checkbox) => (checkbox.element as HTMLInputElement).disabled,
        ),
      ).toBe(true);
      expect(wrapper.find("#dashboard-boundary-opacity").exists()).toBe(true);

      const only = wrapper.get(
        `button[aria-label="Select only ${label} for Map layers"]`,
      );
      expect((only.element as HTMLButtonElement).disabled).toBe(false);
      await only.trigger("click");

      expect(routerReplace).toHaveBeenLastCalledWith({
        query: { layers: queryValue },
      });

      // Route props are owned by the page in production. Mirror that update so
      // the component's full post-navigation state is covered here.
      await wrapper.setProps({ layers: [layer] });
      await nextTick();

      expect(
        (wrapper.get("#dashboard-boundary-layer").element as HTMLSelectElement)
          .value,
      ).toBe("");
      expect(wrapper.find("#dashboard-boundary-opacity").exists()).toBe(false);
      for (const [index, expectedLayer] of [
        "point-locations",
        "heat-map",
        "hot-spots-by-street-block",
      ].entries()) {
        const checkbox = wrapper.get(`#dashboard-map-layer-${index}`)
          .element as HTMLInputElement;
        expect(checkbox.disabled).toBe(false);
        expect(checkbox.checked).toBe(expectedLayer === layer);
      }
      expect(
        wrapper.findComponent(PointMapStub).props("layers"),
      ).toEqual([layer]);

      wrapper.unmount();
    },
  );

  it("shows an honest loading failure and retries the same year", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(textResponse("", 503))
      .mockResolvedValueOnce(jsonResponse(shootingsMeta))
      .mockResolvedValueOnce(textResponse(rowsNdjson));
    vi.stubGlobal("fetch", fetcher);
    const wrapper = mountExplorer();

    await vi.waitFor(() =>
      expect(wrapper.text()).toContain(
        "Detailed records are temporarily unavailable",
      ),
    );
    expect(wrapper.text()).not.toContain("treated as zero");
    expect(wrapper.get("#charts").text()).toContain(
      "Charts are unavailable while detailed records cannot be loaded.",
    );

    await wrapper.get('button[type="button"]').trigger("click");
    await vi.waitFor(() =>
      expect(wrapper.get(".civic-legacy-sidebar__count").text()).toContain(
        "3 shooting victims",
      ),
    );
    expect(fetcher).toHaveBeenCalledTimes(3);
    wrapper.unmount();
  });

  it("aborts the selected-year request when the explorer unmounts", async () => {
    let signal: AbortSignal | undefined;
    const fetcher = vi.fn((_url: string, init?: RequestInit) => {
      signal = init?.signal ?? undefined;
      return new Promise<Response>((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      });
    });
    vi.stubGlobal("fetch", fetcher);
    const wrapper = mountExplorer();

    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    wrapper.unmount();
    expect(signal?.aborted).toBe(true);
  });

  it("loads every manifest-provided feed for All Years before revealing the explorer", async () => {
    const firstRows = shootingRows.slice(0, 2);
    const secondRows = shootingRows.slice(2);
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          rows: 99,
          years_meta: {
            2025: { rows: 2, rows_url: "/opaque/2025.ndjson" },
            2026: { rows: 2, rows_url: "/opaque/2026.ndjson" },
          },
        }),
      )
      .mockResolvedValueOnce(
        textResponse(firstRows.map((row) => JSON.stringify(row)).join("\n")),
      )
      .mockResolvedValueOnce(
        textResponse(secondRows.map((row) => JSON.stringify(row)).join("\n")),
      );
    vi.stubGlobal("fetch", fetcher);
    const wrapper = mountExplorer(null);

    expect(wrapper.text()).toContain(
      "Loading all years record filters and locations",
    );
    expect(wrapper.find(".civic-legacy-map-explorer").exists()).toBe(false);
    await vi.waitFor(() =>
      expect(wrapper.get('[data-test="point-map"]').text()).toContain(
        "all years",
      ),
    );

    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "https://api.example.test/shootings/meta",
      "https://api.example.test/opaque/2026.ndjson",
      "https://api.example.test/opaque/2025.ndjson",
    ]);
    expect(wrapper.emitted("summary")?.at(-1)).toEqual([
      { fatal: 2, mapped: 3, nonfatal: 2, total: 4 },
    ]);
    wrapper.unmount();
  });
});
