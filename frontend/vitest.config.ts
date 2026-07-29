import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import vuetify from "vite-plugin-vuetify";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [vue(), vuetify({ autoImport: true })],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
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
