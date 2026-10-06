import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const layerDirectory = dirname(fileURLToPath(import.meta.url));
const frontendDirectory = resolve(layerDirectory, "../..");

export default defineNuxtConfig({
  css: [resolve(layerDirectory, "app/assets/styles/styles.scss")],
  vite: {
    css: {
      preprocessorOptions: {
        scss: {
          api: "modern-compiler",
          quietDeps: true,
          loadPaths: [
            resolve(
              frontendDirectory,
              "node_modules/@uswds/uswds/packages",
            ),
            resolve(layerDirectory, "app/assets/styles"),
          ],
        },
      },
    },
  },
});
