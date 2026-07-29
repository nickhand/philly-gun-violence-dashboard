import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import vueDevTools from "vite-plugin-vue-devtools";
import vuetify from "vite-plugin-vuetify";
import { fileURLToPath, URL } from "node:url";

export default defineConfig(({ command }) => ({
  base: process.env.VITE_PUBLIC_BASE ?? "/philly-gun-violence-map/",
  plugins: [
    vue(),
    ...(process.env.VITE_E2E ? [] : [vueDevTools()]),
    vuetify({ autoImport: true }),
  ],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    // The manifest powers compressed-size budgets in scripts/check-bundle-size.mjs.
    manifest: true,
    // MapLibre is intentionally isolated in a non-blocking async chunk. Gzipped
    // transfer-size limits are enforced separately by npm run check:bundle.
    chunkSizeWarningLimit: 900,
  },
}));
