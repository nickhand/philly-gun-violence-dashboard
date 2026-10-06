import { describe, expect, it } from "vitest";
import { getFilterConfigs } from "@/features/explorer/config/filters";
import { useArquero } from "@/pages/composables/useArquero";
import { shootingRows } from "../../fixtures/shootings";

describe("useArquero", () => {
  it("keeps non-geocoded records in filtered rows but not map features", () => {
    const arquero = useArquero();
    arquero.initialize(shootingRows, getFilterConfigs(2026));

    expect(arquero.filteredRows.value).toHaveLength(4);
    expect(arquero.filteredFeatures.value).toHaveLength(3);

    arquero.applyFilter("fatal", true);

    expect(arquero.filteredRows.value).toHaveLength(2);
    expect(arquero.filteredFeatures.value).toHaveLength(1);
    expect(arquero.getCategoryCounts("sex")).toEqual(new Map([["M", 2]]));
  });

  it("resets one or all filters without rebuilding the table", () => {
    const arquero = useArquero();
    arquero.initialize(shootingRows, getFilterConfigs(2026));

    arquero.applyFilter("fatal", true);
    arquero.applyFilter("sex", ["M"]);
    expect(arquero.activeFilters.value.size).toBe(2);

    arquero.resetFilter("fatal");
    expect(arquero.activeFilters.value.has("fatal")).toBe(false);

    arquero.resetAllFilters();
    expect(arquero.activeFilters.value.size).toBe(0);
    expect(arquero.filteredRows.value).toHaveLength(4);
  });

  it("preserves unknown ages unless exclude-missing is selected", () => {
    const arquero = useArquero();
    arquero.initialize(shootingRows, getFilterConfigs(2026));

    arquero.applyFilter("age", {
      value: [20, 40],
      excludeMissing: false,
    });
    expect(arquero.filteredRows.value.map((row) => row.unique_id)).toEqual([
      1, 2, 4,
    ]);

    arquero.applyFilter("age", {
      value: [20, 40],
      excludeMissing: true,
    });
    expect(arquero.filteredRows.value.map((row) => row.unique_id)).toEqual([
      1, 2,
    ]);
  });
});
