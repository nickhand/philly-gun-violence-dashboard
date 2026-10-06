import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { defineNuxtModule } from "nuxt/kit";

/**
 * Persist the client build manifest for `npm run check:bundle`. Nuxt compiles
 * this manifest into the server bundle, and enabling Vite's own manifest would
 * publish it under `_nuxt/`. Production builds use a cache build directory, so
 * write to the project's `.nuxt/` where the budget script can find it.
 */
export default defineNuxtModule({
  meta: { name: "client-bundle-manifest" },
  setup(_options, nuxt) {
    if (nuxt.options.dev) return;
    const outputDirectory = join(nuxt.options.rootDir, ".nuxt");
    nuxt.hook("build:manifest", async (manifest) => {
      await mkdir(outputDirectory, { recursive: true });
      await writeFile(
        join(outputDirectory, "client-bundle-manifest.json"),
        `${JSON.stringify(manifest, null, 2)}\n`,
        "utf8",
      );
    });
  },
});
