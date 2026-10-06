import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const assetsRoot = join(frontendRoot, ".output", "public", "_nuxt");
// Written by modules/client-bundle-manifest.ts during `nuxt build`.
const manifestPath = join(frontendRoot, ".nuxt", "client-bundle-manifest.json");

if (!existsSync(manifestPath) || !existsSync(assetsRoot)) {
  throw new Error("Run `npm run build` before checking bundle sizes.");
}

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));

const ENTRY_KEY = "../node_modules/nuxt/dist/app/entry.js";
const LAYOUT_KEY = "layouts/default.vue";
const DASHBOARD_PAGE_KEY = "pages/index.vue";
const EXPLORER_KEY = "components/DashboardExplorer.client.vue";
const MAPLIBRE_KEY = "../node_modules/maplibre-gl/dist/maplibre-gl.mjs";
const MAPLIBRE_CSS_KEY = "../node_modules/maplibre-gl/dist/maplibre-gl.css";
const ANALYTICS_KEY = "../node_modules/posthog-js/dist/module.mjs";

// Fonts are declared by the entry stylesheet but fetched only for the faces a
// page renders, so budgets cover the JavaScript and CSS each route must load.
function collectChunkFiles(key, files = new Set()) {
  const chunk = manifest[key];
  if (!chunk) {
    throw new Error(`Missing client manifest entry: ${key}`);
  }

  files.add(chunk.file);
  for (const file of chunk.css ?? []) files.add(file);
  for (const importedKey of chunk.imports ?? []) {
    collectChunkFiles(importedKey, files);
  }

  return files;
}

function union(...sets) {
  return new Set(sets.flatMap((set) => [...set]));
}

function gzipSize(files) {
  return [...files].reduce((total, file) => {
    const contents = readFileSync(join(assetsRoot, file));
    return total + gzipSync(contents, { level: 9 }).byteLength;
  }, 0);
}

function formatSize(bytes) {
  return `${(bytes / 1024).toFixed(1)} KiB`;
}

const appShellFiles = collectChunkFiles(ENTRY_KEY);
const dashboardFiles = union(
  appShellFiles,
  collectChunkFiles(LAYOUT_KEY),
  collectChunkFiles(DASHBOARD_PAGE_KEY),
);
// The explorer is client-only and loads MapLibre and its stylesheet on demand.
const explorerFiles = union(
  collectChunkFiles(EXPLORER_KEY),
  collectChunkFiles(MAPLIBRE_KEY),
  collectChunkFiles(MAPLIBRE_CSS_KEY),
);
// MapLibre 6 loads a separately bundled worker that the client manifest does
// not list, so include it explicitly rather than hiding its transfer cost.
const mapWorkerFiles = new Set(
  readdirSync(assetsRoot).filter((file) =>
    /^maplibre-gl-worker-[\w-]+\.js$/.test(file),
  ),
);
if (mapWorkerFiles.size !== 1) {
  throw new Error("Expected exactly one bundled MapLibre worker");
}
const analyticsFiles = collectChunkFiles(ANALYTICS_KEY);

const budgets = [
  {
    label: "app shell",
    files: appShellFiles,
    // Nuxt runtime, router, and shared civic UI: measured at 101 KB gzip.
    maxBytes: 107_000,
  },
  {
    label: "dashboard route",
    files: dashboardFiles,
    maxBytes: 120_000,
  },
  {
    label: "interactive explorer + map",
    files: explorerFiles,
    // Explorer chunk plus MapLibre 6 and its stylesheet: measured at 395 KB.
    maxBytes: 415_000,
  },
  {
    label: "map worker",
    files: mapWorkerFiles,
    maxBytes: 155_000,
  },
  {
    label: "dashboard + explorer + worker",
    files: union(dashboardFiles, explorerFiles, mapWorkerFiles),
    maxBytes: 620_000,
  },
  {
    label: "deferred analytics",
    files: analyticsFiles,
    // PostHog loads after first render: measured at 95 KB gzip.
    maxBytes: 100_000,
  },
];

let failed = false;

for (const budget of budgets) {
  const actualBytes = gzipSize(budget.files);
  const withinBudget = actualBytes <= budget.maxBytes;
  const marker = withinBudget ? "✓" : "✗";
  console.log(
    `${marker} ${budget.label}: ${formatSize(actualBytes)} / ${formatSize(budget.maxBytes)}`,
  );
  failed ||= !withinBudget;
}

if (failed) {
  process.exitCode = 1;
}
