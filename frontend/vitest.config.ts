import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import vuetify from "vite-plugin-vuetify";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [vue(), vuetify({ autoImport: true })],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "~": fileURLToPath(new URL("./app", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/unit/**/*.spec.ts"],
    server: {
      deps: {
        inline: [/vuetify/],
      },
    },
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
        "app/utils/mapLayers.ts",
        "app/utils/mapOverlays.ts",
        "app/utils/mapView.ts",
        "app/utils/shootingDownloads.ts",
        "app/utils/shootingFilters.ts",
        "app/utils/shootingRecords.ts",
        "src/shared/utils/**/*.ts",
        "src/pages/composables/useArquero.ts",
        "src/pages/composables/useDownload.ts",
        "src/features/explorer/components/MapSidebar/filters/FilterPanel.vue",
        "src/features/explorer/components/MapSidebar/filters/SwitchFilter.vue",
        "src/features/explorer/components/MapView/AddressSearch.vue",
        "src/features/charts/components/HistogramChart.vue",
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
