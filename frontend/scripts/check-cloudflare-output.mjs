import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const output = join(root, ".output");
const workerEntry = join(output, "server", "index.mjs");
const publicDirectory = join(output, "public");
const appPublicDirectory = join(publicDirectory, "philly-gun-violence-map");
const config = JSON.parse(readFileSync(join(root, "wrangler.jsonc"), "utf8"));
const packageJson = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
const installedVue = JSON.parse(
  readFileSync(join(root, "node_modules", "vue", "package.json"), "utf8"),
);
const installedVueRouter = JSON.parse(
  readFileSync(join(root, "node_modules", "vue-router", "package.json"), "utf8"),
);
const environmentName = process.argv[2];
const environment = config.env?.[environmentName];
const hstsHeader = /Strict-Transport-Security/i;

function readJavaScriptTree(directory) {
  return readdirSync(directory, { withFileTypes: true })
    .flatMap((entry) => {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) return readJavaScriptTree(path);
      return entry.name.endsWith(".mjs") ? [readFileSync(path, "utf8")] : [];
    })
    .join("\n");
}

assert.ok(
  environmentName === "staging" || environmentName === "production",
  "Pass either staging or production to the Cloudflare output checker.",
);
assert.equal(config.name, "philly-gun-violence-dashboard");
assert.equal(config.main, ".output/server/index.mjs");
assert.equal(config.assets?.directory, ".output/public");
assert.ok(config.compatibility_flags?.includes("nodejs_compat"));
assert.equal(config.observability?.enabled, true);
assert.equal(
  packageJson.dependencies?.vue,
  installedVue.version,
  "The app and Nuxt must use one Vue runtime or Cloudflare SSR can emit unresolved links.",
);
assert.equal(
  packageJson.dependencies?.["vue-router"],
  installedVueRouter.version,
  "The app and Nuxt must use one Vue Router runtime or hydration can mismatch.",
);
assert.ok(
  !existsSync(join(root, "node_modules", "nuxt", "node_modules", "vue")),
  "Nuxt unexpectedly installed a second Vue runtime.",
);
assert.ok(
  !existsSync(join(root, "node_modules", "nuxt", "node_modules", "vue-router")),
  "Nuxt unexpectedly installed a second Vue Router runtime.",
);
assert.ok(environment, `Wrangler is missing its ${environmentName} environment.`);
assert.equal(
  environment.vars?.NUXT_PUBLIC_DOWNLOADS_BASE_URL,
  "https://d2cemhjkwenjmb.cloudfront.net",
);
assert.equal(
  environment.vars?.NUXT_PUBLIC_API_BASE_URL,
  "https://philly-gun-violence-dashboard-api.fly.dev",
);

if (environmentName === "staging") {
  assert.equal(environment.workers_dev, true);
  assert.equal(environment.routes, undefined);
  assert.equal(environment.vars?.NUXT_PUBLIC_INDEXABLE, "false");
} else {
  assert.equal(environment.workers_dev, false);
  assert.equal(environment.vars?.NUXT_PUBLIC_INDEXABLE, "true");
  assert.deepEqual(
    environment.routes,
    [
      "www.nickhand.dev/philly-gun-violence-map",
      "www.nickhand.dev/philly-gun-violence-map/*",
    ].map((pattern) => ({ pattern, zone_name: "nickhand.dev" })),
  );
}

assert.ok(existsSync(workerEntry), "Cloudflare worker entry was not generated.");
assert.ok(
  existsSync(join(appPublicDirectory, "_nuxt")),
  "Cloudflare static assets were not generated.",
);
assert.ok(
  !existsSync(join(root, ".wrangler", "deploy", "config.json")),
  "Nitro unexpectedly generated a hidden deployment-config redirect.",
);

const cloudflareHeaders = readFileSync(join(publicDirectory, "_headers"), "utf8");
const workerJavaScript = readJavaScriptTree(join(output, "server"));
assert.match(cloudflareHeaders, /philly-gun-violence-map\/_nuxt/);
if (environmentName === "staging") {
  assert.match(
    cloudflareHeaders,
    /X-Robots-Tag: noindex, nofollow/,
    "The staging assets were built without the crawler noindex policy.",
  );
  assert.doesNotMatch(
    `${cloudflareHeaders}\n${workerJavaScript}`,
    hstsHeader,
    "The workers.dev staging build must not publish an HSTS policy.",
  );
} else {
  assert.doesNotMatch(
    cloudflareHeaders,
    /X-Robots-Tag: noindex, nofollow/,
    "The production assets still contain the staging noindex policy.",
  );
  assert.match(
    cloudflareHeaders,
    hstsHeader,
    "The production static-asset headers are missing the HSTS policy.",
  );
  assert.match(
    workerJavaScript,
    hstsHeader,
    "The production Worker routes are missing the HSTS policy.",
  );
}

console.log(
  `Cloudflare ${environmentName} output is complete${
    environmentName === "staging" ? " and explicitly noindex" : " and indexable"
  }.`,
);
