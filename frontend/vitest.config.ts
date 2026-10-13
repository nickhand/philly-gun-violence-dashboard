import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "~": fileURLToPath(new URL("./app", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/unit/**/*.spec.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov"],
      reportsDirectory: "./coverage",
      include: [
        "layers/civic-ui/app/components/CivicCheckboxField.vue",
        "layers/civic-ui/app/components/CivicCopyButton.vue",
        "layers/civic-ui/app/components/CivicDisclosurePanel.vue",
        "layers/civic-ui/app/components/CivicInfoTooltip.vue",
        "layers/civic-ui/app/components/CivicRangeField.vue",
        "layers/civic-ui/app/components/CivicSelectField.vue",
        "layers/civic-ui/app/components/CivicSiteFooter.vue",
        "layers/civic-ui/app/components/CivicSiteHeader.vue",
        "app/components/DashboardAddressSearch.vue",
        "app/components/DashboardCategoryCharts.vue",
        "app/components/DashboardCheckboxFilter.vue",
        "app/components/DashboardDownloadPanel.vue",
        "app/components/DashboardExplorer.client.vue",
        "app/components/DashboardFilterPanel.vue",
        "app/components/DashboardPointMap.client.vue",
        "app/components/DashboardRangeFilter.vue",
        "app/utils/geocoding.ts",
        "app/utils/analytics.ts",
        "app/utils/mapLayers.ts",
        "app/utils/mapOverlays.ts",
        "app/utils/mapPrint.ts",
        "app/utils/mapView.ts",
        "app/utils/shootingDownloads.ts",
        "app/utils/shootingFilters.ts",
        "app/utils/shootingRecords.ts",
      ],
      thresholds: {
        statements: 70,
        branches: 60,
        functions: 70,
        lines: 70,
      },
    },
  },
});
