import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const output = join(root, ".output");
const workerEntry = join(output, "server", "index.mjs");
const publicDirectory = join(output, "public");
const appPublicDirectory = join(publicDirectory, "philly-gun-violence-map");
const config = JSON.parse(readFileSync(join(root, "wrangler.jsonc"), "utf8"));
const environmentName = process.argv[2];
const environment = config.env?.[environmentName];

assert.ok(
  environmentName === "staging" || environmentName === "production",
  "Pass either staging or production to the Cloudflare output checker.",
);
assert.equal(config.name, "philly-gun-violence-dashboard");
assert.equal(config.main, ".output/server/index.mjs");
assert.equal(config.assets?.directory, ".output/public");
assert.ok(config.compatibility_flags?.includes("nodejs_compat"));
assert.equal(config.observability?.enabled, true);
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
assert.match(cloudflareHeaders, /philly-gun-violence-map\/_nuxt/);
if (environmentName === "staging") {
  assert.match(
    cloudflareHeaders,
    /X-Robots-Tag: noindex, nofollow/,
    "The staging assets were built without the crawler noindex policy.",
  );
} else {
  assert.doesNotMatch(
    cloudflareHeaders,
    /X-Robots-Tag: noindex, nofollow/,
    "The production assets still contain the staging noindex policy.",
  );
}

console.log(
  `Cloudflare ${environmentName} output is complete${
    environmentName === "staging" ? " and explicitly noindex" : " and indexable"
  }.`,
);
