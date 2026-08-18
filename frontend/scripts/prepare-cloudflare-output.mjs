import { copyFileSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const publicDirectory = join(root, ".output", "public");
const generatedHeaders = join(
  publicDirectory,
  "philly-gun-violence-map",
  "_headers",
);
const cloudflareHeaders = join(publicDirectory, "_headers");

if (!existsSync(generatedHeaders)) {
  throw new Error("Nuxt did not generate the expected static-asset _headers file.");
}

// Workers Static Assets only reads _headers from the configured asset root.
// Nitro emits it below the Nuxt base path, so promote the generated file
// without changing its already base-prefixed rules.
copyFileSync(generatedHeaders, cloudflareHeaders);
