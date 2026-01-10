import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import vueDevTools from "vite-plugin-vue-devtools";
import vuetify from "vite-plugin-vuetify";
import { fileURLToPath, URL } from "node:url";

export default defineConfig(({ mode }) => ({
  // Use root for dev, full URL for production
  base:
    mode === "production"
      ? "https://www.nickhand.dev/philly-gun-violence-map/"
      : "/",
  plugins: [
    vue(),
    vueDevTools(),
    vuetify({ autoImport: true }),
    // Inject base tag only in production builds
    {
      name: "inject-base-tag",
      transformIndexHtml(html, ctx) {
        if (ctx.bundle) {
          // Production build
          return html.replace(
            "<head>",
            '<head>\n    <base href="https://www.nickhand.dev/philly-gun-violence-map/" />'
          );
        }
        return html;
      },
    },
  ],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
}));
