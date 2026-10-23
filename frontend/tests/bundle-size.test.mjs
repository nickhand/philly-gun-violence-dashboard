import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

function checkBundle({
  workerInManifest = true,
  shell = 100_000,
  map = 330_000,
  worker = 140_000,
  analytics = 90_000,
  analyticsExtension = 0,
  preloadAnalytics = false,
} = {}) {
  const root = mkdtempSync(join(tmpdir(), "frontend-bundle-budget-"));
  try {
    const assets = join(root, ".output/public/_nuxt");
    const virtual = join(root, ".output/server/chunks/virtual");
    mkdirSync(assets, { recursive: true });
    mkdirSync(virtual, { recursive: true });
    mkdirSync(join(root, "scripts"));
    copyFileSync(new URL("../scripts/check-bundle-size.mjs", import.meta.url), join(root, "scripts/check-bundle-size.mjs"));
    for (const [file, bytes] of Object.entries({
      "shell.js": shell,
      "map.js": map,
      "maplibre-gl-worker-test.js": worker,
      "analytics.js": analytics,
      "analytics-extension.js": analyticsExtension,
      "map.css": 0,
    })) {
      writeFileSync(join(assets, file), randomBytes(bytes));
    }
    const preload = (...files) => ({ preload: Object.fromEntries(files.map((file) => [file, { file }])) });
    const manifest = {
      entrypoints: ["entry"],
      dependencies: {
        entry: preload("shell.js", ...(preloadAnalytics ? ["analytics-extension.js"] : [])),
        "layouts/default.vue": preload("shell.js"),
        "components/DashboardExplorer.client.vue": preload("shell.js", "map.js", ...(workerInManifest ? ["maplibre-gl-worker-test.js"] : [])),
        "../node_modules/maplibre-gl/dist/maplibre-gl.mjs": preload("map.js"),
        "../node_modules/maplibre-gl/dist/maplibre-gl.css": preload("map.css"),
        "../node_modules/posthog-js/dist/module.mjs": preload("analytics.js", "analytics-extension.js"),
      },
    };
    writeFileSync(join(virtual, "precomputed.mjs"), `export default ${JSON.stringify(manifest)};`);
    return spawnSync(process.execPath, [join(root, "scripts/check-bundle-size.mjs")], { encoding: "utf8" });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

for (const workerInManifest of [false, true]) {
  test(`budgets map and worker separately with workerInManifest=${workerInManifest}`, () => {
    const result = checkBundle({ workerInManifest });
    assert.equal(result.status, 0, result.stdout + result.stderr);
  });
}

test("a worker over its dedicated budget still fails", () => {
  const result = checkBundle({ worker: 160_000 });
  assert.equal(result.status, 1);
  assert.match(result.stdout, /✗ map worker:/);
});

test("the combined budget includes the full worker transfer", () => {
  const result = checkBundle({ shell: 109_000, map: 354_000, worker: 154_000 });
  assert.equal(result.status, 1);
  assert.match(result.stdout, /✓ app shell:/);
  assert.match(result.stdout, /✓ interactive map/);
  assert.match(result.stdout, /✓ map worker:/);
  assert.match(result.stdout, /✗ app shell \+ map \+ worker:/);
});

test("the analytics budget includes SDK extension chunks", () => {
  const result = checkBundle({ analytics: 90_000, analyticsExtension: 15_000 });
  assert.equal(result.status, 1);
  assert.match(result.stdout, /✗ deferred analytics:/);
});

test("analytics extensions must remain outside the app shell", () => {
  const result = checkBundle({ preloadAnalytics: true });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Analytics must stay deferred/);
});
