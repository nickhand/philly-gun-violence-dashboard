import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, nextTick } from "vue";
import { VExpansionPanels } from "vuetify/components";
import { vuetify } from "@/app/vuetify";
import AddressSearch from "@/features/explorer/components/MapView/AddressSearch.vue";
import FilterPanel from "@/features/explorer/components/MapSidebar/filters/FilterPanel.vue";
import SwitchFilter from "@/features/explorer/components/MapSidebar/filters/SwitchFilter.vue";
import HistogramChart from "@/features/charts/components/HistogramChart.vue";
import { shootingRows } from "../../fixtures/shootings";

vi.mock("@/shared/analytics", () => ({
  track: vi.fn(),
}));

const mountOptions = {
  attachTo: document.body,
  global: {
    plugins: [vuetify],
  },
};

describe("filter control semantics", () => {
  it("renders reset as a keyboard-operable sibling of the expansion button", async () => {
    const Harness = defineComponent({
      components: { FilterPanel, VExpansionPanels },
      template: `
        <v-expansion-panels>
          <FilterPanel label="Gender" show-reset>
            <p>Filter options</p>
          </FilterPanel>
        </v-expansion-panels>
      `,
    });
    const wrapper = mount(Harness, {
      ...mountOptions,
    });

    const reset = wrapper.get('button[aria-label="Reset Gender filter"]');
    await reset.trigger("click");

    expect(wrapper.find("button button").exists()).toBe(false);
    expect(wrapper.findComponent(FilterPanel).emitted("reset")).toHaveLength(1);
  });

  it("does not nest a switch inside an expansion button", () => {
    const Harness = defineComponent({
      components: { SwitchFilter, VExpansionPanels },
      template: `
        <v-expansion-panels>
          <SwitchFilter
            :model-value="false"
            label="Fatal shootings only"
          />
        </v-expansion-panels>
      `,
    });
    const wrapper = mount(Harness, {
      ...mountOptions,
    });

    const checkbox = wrapper.get('input[type="checkbox"]').element;
    expect(checkbox.closest("button")).toBeNull();
    expect(checkbox.getAttribute("aria-label")).toBe(
      "Fatal shootings only",
    );
  });
});

describe("AddressSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [
          {
            place_id: 123,
            display_name: "123 Market Street, Philadelphia, PA",
            lat: "39.9526",
            lon: "-75.1602",
            type: "house",
            importance: 0.8,
            address: {
              house_number: "123",
              road: "Market Street",
              city: "Philadelphia",
              postcode: "19107",
            },
          },
        ],
      }),
    );
  });

  it("implements the combobox keyboard and active-descendant pattern", async () => {
    const wrapper = mount(AddressSearch, mountOptions);
    const input = wrapper.get('input[role="combobox"]');

    expect(input.attributes("aria-expanded")).toBe("false");
    expect(input.attributes("aria-controls")).toBe("address-search-results");

    await input.setValue("123 Market");
    await vi.advanceTimersByTimeAsync(300);
    await nextTick();

    expect(input.attributes("aria-expanded")).toBe("true");
    await input.trigger("keydown", { key: "ArrowDown" });
    expect(input.attributes("aria-activedescendant")).toBe(
      "address-search-result-0",
    );

    await input.trigger("keydown", { key: "Enter" });
    expect(wrapper.emitted("select")?.[0]?.[0]).toMatchObject({
      id: 123,
      shortName: "123 Market Street, 19107",
    });
  });
});

describe("HistogramChart", () => {
  it("exposes the complete distribution in a semantic table", () => {
    const wrapper = mount(HistogramChart, {
      ...mountOptions,
      props: {
        rows: shootingRows,
        title: "Outcome",
        accessor: "fatal",
        color: "#906050",
        categories: [true, false],
        aliases: { true: "Fatal", false: "Nonfatal" },
      },
    });

    const table = wrapper.get(
      'table[aria-label="Outcome distribution breakdown"]',
    );
    expect(table.text()).toContain("Fatal250%");
    expect(table.text()).toContain("Nonfatal250%");
    expect(wrapper.get("svg").attributes("aria-hidden")).toBe("true");
  });
});
