import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { gzipSync } from "node:zlib";

// Run after `npm run build:nuxt`. Nuxt embeds Vite's client manifest in the
// server build as vue-bundle-renderer's precomputed dependency graph, so the
// budgets read chunk relationships from there and file sizes from the public
// assets. Fail loudly if a Nuxt upgrade moves either.
const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const publicAssets = join(frontendRoot, ".output", "public", "_nuxt");
const precomputedPath = join(
  frontendRoot,
  ".output",
  "server",
  "chunks",
  "virtual",
  "precomputed.mjs",
);
if (!existsSync(precomputedPath) || !existsSync(publicAssets)) {
  throw new Error("Missing Nuxt build output; run `npm run build:nuxt` first");
}
const { default: precomputed } = await import(pathToFileURL(precomputedPath).href);

const LAYOUT_KEY = "layouts/default.vue";
const EXPLORER_KEY = "components/DashboardExplorer.client.vue";
const MAPLIBRE_KEY = "../node_modules/maplibre-gl/dist/maplibre-gl.mjs";
const MAPLIBRE_CSS_KEY = "../node_modules/maplibre-gl/dist/maplibre-gl.css";
const ANALYTICS_KEY = "../node_modules/posthog-js/dist/module.mjs";

// Files a browser fetches for a module: the chunk itself plus what it preloads.
function preloadFiles(key) {
  const dependencies = precomputed.dependencies[key];
  if (!dependencies) {
    throw new Error(`Missing Nuxt client manifest entry: ${key}`);
  }
  return new Set(Object.values(dependencies.preload).map(({ file }) => file));
}

function gzipSize(files) {
  return [...files].reduce((total, file) => {
    const contents = readFileSync(join(publicAssets, file));
    return total + gzipSync(contents, { level: 9 }).byteLength;
  }, 0);
}

function formatSize(bytes) {
  return `${(bytes / 1024).toFixed(1)} KiB`;
}

if (precomputed.entrypoints.length !== 1) {
  throw new Error("Expected exactly one Nuxt client entrypoint");
}
const appShellFiles = new Set([
  ...preloadFiles(precomputed.entrypoints[0]),
  ...preloadFiles(LAYOUT_KEY),
]);
const mapFiles = new Set(
  [
    ...preloadFiles(EXPLORER_KEY),
    ...preloadFiles(MAPLIBRE_KEY),
    ...preloadFiles(MAPLIBRE_CSS_KEY),
  ].filter((file) => !appShellFiles.has(file)),
);
// MapLibre 6 loads a separately bundled worker that the client manifest does
// not list, so include it explicitly rather than hiding its transfer cost.
const mapWorkerFiles = new Set(
  readdirSync(publicAssets).filter((file) =>
    /^maplibre-gl-worker-[\w-]+\.js$/.test(file),
  ),
);
if (mapWorkerFiles.size !== 1) {
  throw new Error("Expected exactly one bundled MapLibre worker");
}
const analyticsFiles = preloadFiles(ANALYTICS_KEY);
for (const file of analyticsFiles) {
  if (appShellFiles.has(file)) {
    throw new Error(`Analytics must stay deferred, but the app shell preloads ${file}`);
  }
}
const coreExperienceFiles = new Set([...appShellFiles, ...mapFiles, ...mapWorkerFiles]);

// Budgets sit about 5% above the gzip sizes measured when the Nuxt app replaced
// the legacy bundle (October 2026), so growth is a deliberate decision.
const budgets = [
  {
    label: "app shell",
    files: appShellFiles,
    // Measured 101.3 KiB.
    maxBytes: 110_000,
  },
  {
    label: "interactive map (explorer + MapLibre)",
    files: mapFiles,
    // Measured 330.6 KiB.
    maxBytes: 355_000,
  },
  {
    label: "map worker",
    files: mapWorkerFiles,
    // Measured 141.4 KiB.
    maxBytes: 155_000,
  },
  {
    label: "app shell + map + worker",
    files: coreExperienceFiles,
    // Measured 573.3 KiB.
    maxBytes: 615_000,
  },
  {
    label: "deferred analytics",
    files: analyticsFiles,
    // Measured 92.6 KiB.
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

const iconFontAssets = readdirSync(publicAssets).filter((file) =>
  /materialdesignicons.*\.(?:eot|ttf|woff2?)$/.test(file),
);

if (iconFontAssets.length > 0) {
  console.error(
    `✗ unexpected Material Design icon-font assets: ${iconFontAssets.join(", ")}`,
  );
  failed = true;
} else {
  console.log("✓ no bundled Material Design icon-font assets");
}

if (failed) {
  process.exitCode = 1;
}
