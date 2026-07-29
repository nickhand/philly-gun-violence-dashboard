import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const distRoot = join(frontendRoot, "dist");
const manifest = JSON.parse(
  readFileSync(join(distRoot, ".vite", "manifest.json"), "utf8"),
);

const ENTRY_KEY = "index.html";
const MAP_KEY = "src/features/explorer/components/MapView/MapCanvas.vue";
const ANALYTICS_KEY = "node_modules/posthog-js/dist/module.js";

function collectChunkFiles(key, includeImports = false, files = new Set()) {
  const chunk = manifest[key];
  if (!chunk) {
    throw new Error(`Missing Vite manifest entry: ${key}`);
  }

  files.add(chunk.file);
  for (const file of chunk.css ?? []) files.add(file);
  for (const file of chunk.assets ?? []) files.add(file);

  if (includeImports) {
    for (const importedKey of chunk.imports ?? []) {
      collectChunkFiles(importedKey, true, files);
    }
  }

  return files;
}

function gzipSize(files) {
  return [...files].reduce((total, file) => {
    const contents = readFileSync(join(distRoot, file));
    return total + gzipSync(contents, { level: 9 }).byteLength;
  }, 0);
}

function formatSize(bytes) {
  return `${(bytes / 1024).toFixed(1)} KiB`;
}

const appShellFiles = collectChunkFiles(ENTRY_KEY, true);
appShellFiles.add("index.html");
const mapFiles = collectChunkFiles(MAP_KEY);
const analyticsFiles = manifest[ANALYTICS_KEY]
  ? collectChunkFiles(ANALYTICS_KEY)
  : new Set();
const coreExperienceFiles = new Set([...appShellFiles, ...mapFiles]);

const budgets = [
  {
    label: "app shell",
    files: appShellFiles,
    maxBytes: 315_000,
  },
  {
    label: "interactive map",
    files: mapFiles,
    maxBytes: 240_000,
  },
  {
    label: "app shell + map",
    files: coreExperienceFiles,
    maxBytes: 555_000,
  },
  {
    label: "deferred analytics",
    files: analyticsFiles,
    maxBytes: 65_000,
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

const iconFontAssets = readdirSync(join(distRoot, "assets")).filter((file) =>
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
