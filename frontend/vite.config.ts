import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import vueDevTools from "vite-plugin-vue-devtools";
import vuetify from "vite-plugin-vuetify";
import { fileURLToPath, URL } from "node:url";

export default defineConfig(({ command }) => ({
  base: "/",
  plugins: [
    vue(),
    vueDevTools(),
    vuetify({ autoImport: true }),
    // Inject base tag only in production builds
    {
      name: "inject-base-tag",
      transformIndexHtml(html) {
        if (command === "build") {
          return html.replace(
            "<head>",
            '<head>\n    <base href="https://phillygunviolence.netlify.app/" />'
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
