import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MappingDashboard from "@/pages/components/MappingDashboard.vue";
import { useHomicidesStore } from "@/shared/stores/homicides";
import { useShootingsStore } from "@/shared/stores/shootings";
import { shootingRows } from "../../fixtures/shootings";

vi.mock("@/features/explorer/components/MapExplorer.vue", () => ({
  default: {
    name: "MapExplorer",
    emits: ["map-ready"],
    template: "<div>Map loading</div>",
  },
}));

vi.mock("@/features/charts/components/ChartDashboard.vue", () => ({
  default: { template: "<div />" },
}));

vi.mock("@/pages/composables/useUrlState", () => ({
  useUrlState: vi.fn(),
}));

describe("dashboard header readiness", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useShootingsStore().$patch({
      selectedYear: 2026,
      dataYears: [2026],
      loadedYears: new Set([2026]),
      rowsByYear: { 2026: shootingRows },
    });
    useHomicidesStore().totalsCache[2026] = {
      year: 2026,
      annual: null,
      ytd: 10,
    };
  });

  it("shows ready statistics while the map has not emitted map-ready", async () => {
    const wrapper = mount(MappingDashboard);
    await flushPromises();

    expect(wrapper.findComponent({ name: "MapExplorer" }).emitted("map-ready"))
      .toBeUndefined();
    const shootingSummary = wrapper.get(".header-submessage--shooting");
    expect(shootingSummary.attributes("aria-hidden")).toBe("false");
    expect(shootingSummary.text()).toContain("2 nonfatal and 2 fatal");
    expect(wrapper.get(".header-submessage--homicide").text()).toContain("10 homicides");
    wrapper.unmount();
  });

  it("keeps statistics hidden until the selected data has finished loading", async () => {
    const shootings = useShootingsStore();
    shootings.isLoading = true;
    const wrapper = mount(MappingDashboard);
    await flushPromises();

    const shootingSummary = wrapper.get(".header-submessage--shooting");
    expect(shootingSummary.attributes("aria-hidden")).toBe("true");
    expect(shootingSummary.text()).toBe("");

    shootings.isLoading = false;
    await flushPromises();

    expect(shootingSummary.attributes("aria-hidden")).toBe("false");
    expect(shootingSummary.text()).toContain("2 nonfatal and 2 fatal");
    wrapper.unmount();
  });
});
