import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { readFileSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";
import { gzipSync } from "node:zlib";

import { JSDOM } from "jsdom";

const frontendDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const basePath = "/philly-gun-violence-map/";
const canonicalBase = "https://www.nickhand.dev/philly-gun-violence-map";
const downloadsBasePath = "/philly-shooting-records";
const slowDownloadsBasePath = "/slow-philly-shooting-records";
const slowManifestDelayMs = 2_000;
const publicDownloadReleaseId = "a".repeat(64);
const publicDownloadReleasePrefix = `releases/${publicDownloadReleaseId}`;
let downloadsBase;
let allRecordsDownloadUrl;
const manifestRequestUserAgents = [];
const geographicReferenceDownloads = [
  ["ZIP code boundaries", "zip_code", "philadelphia-zip-codes.geojson", 451_447],
  ["Neighborhood boundaries", "neighborhood", "philadelphia-neighborhoods.geojson", 562_605],
  ["Police district boundaries", "police_district", "philadelphia-police-districts.geojson", 293_134],
  ["City Council district boundaries", "council_district", "philadelphia-city-council-districts.geojson", 226_809],
  ["Pennsylvania House district boundaries", "house_district", "philadelphia-pa-house-districts.geojson", 522_824],
  ["Pennsylvania Senate district boundaries", "senate_district", "philadelphia-pa-senate-districts.geojson", 48_328],
  ["Elementary school catchment boundaries", "school_name", "philadelphia-elementary-school-catchments.geojson", 704_686],
  ["Street blocks", "segment_id", "philadelphia-street-blocks.geojson", 8_947_241],
];
const publicDownloadManifest = {
  schema_version: 2,
  version: `sha256:${publicDownloadReleaseId}`,
  published_at: "2026-08-17T19:56:57Z",
  downloads: [
    {
      id: "shooting_victims",
      kind: "records",
      label: "Philadelphia shooting-victim records",
      filename: "philadelphia-shooting-victims.csv",
      path: `${publicDownloadReleasePrefix}/philadelphia-shooting-victims.csv`,
      media_type: "text/csv; charset=utf-8",
      byte_size: 3_064_024,
      sha256: "b".repeat(64),
      row_count: 5,
    },
    ...geographicReferenceDownloads.map(([label, joinField, filename, byteSize]) => ({
      id: {
        "philadelphia-zip-codes.geojson": "zip_codes",
        "philadelphia-neighborhoods.geojson": "neighborhoods",
        "philadelphia-police-districts.geojson": "police_districts",
        "philadelphia-city-council-districts.geojson": "council_districts",
        "philadelphia-pa-house-districts.geojson": "pa_house_districts",
        "philadelphia-pa-senate-districts.geojson": "pa_senate_districts",
        "philadelphia-elementary-school-catchments.geojson": "school_catchments",
        "philadelphia-street-blocks.geojson": "street_blocks",
      }[filename],
      kind: "geography",
      label,
      filename,
      path: `${publicDownloadReleasePrefix}/geography/${filename}`,
      media_type: "application/geo+json",
      byte_size: byteSize,
      sha256: "c".repeat(64),
      row_count: 1,
      dataset: {
        "philadelphia-zip-codes.geojson": "zip_codes",
        "philadelphia-neighborhoods.geojson": "neighborhoods",
        "philadelphia-police-districts.geojson": "police_districts",
        "philadelphia-city-council-districts.geojson": "council_districts",
        "philadelphia-pa-house-districts.geojson": "pa_house_districts",
        "philadelphia-pa-senate-districts.geojson": "pa_senate_districts",
        "philadelphia-elementary-school-catchments.geojson": "school_catchments",
        "philadelphia-street-blocks.geojson": "street_blocks",
      }[filename],
      join_field: joinField,
    })),
  ],
};
const legacyPublicDownloadManifest = {
  schema_version: 1,
  version: "sha256:legacy-public-download-fixture",
  published_at: "2026-08-17T19:56:57Z",
  downloads: [
    {
      filename: "philadelphia-shooting-victims.csv",
      path: "philadelphia-shooting-victims.csv",
      media_type: "text/csv; charset=utf-8",
      byte_size: 3_064_024,
    },
    ...geographicReferenceDownloads.map(([, , filename, byteSize]) => ({
      filename,
      path: `geography/${filename}`,
      media_type: "application/geo+json",
      byte_size: byteSize,
    })),
  ],
};

const meta = {
  shootings: {
    data_through: "2023-01-15",
    last_updated: "2023-01-16T08:00:00Z",
    row_count: 5,
  },
  homicides: {
    data_through: "2023-01-16",
    last_updated: "2023-01-16T09:00:00Z",
  },
  courts: {
    data_through: "2023-01-14",
    last_updated: "2023-01-14T10:00:00Z",
  },
};

const stats = {
  shootings_data_through: "2023-01-15",
  homicides_data_through: "2023-01-16",
  current_year: 2023,
  previous_year: 2022,
  minimum_year: 2022,
  total_victims_all_years: 6,
  current_total: 2,
  current_fatal: 1,
  current_nonfatal: 1,
  shootings_previous_ytd: 1,
  shooting_percent_change: 100,
  homicides_ytd: 80,
  homicides_previous_ytd: 100,
  homicide_percent_change: -20,
  peak: { year: 2022, victims: 3, homicides: 500 },
  years: [
    { year: 2022, victims: 3, homicides: 500 },
    { year: 2023, victims: 2, homicides: 80 },
  ],
};

let apiServer;
let apiOrigin;
let downloadsServer;
let downloadsOrigin;
let nuxtProcess;
let nuxtOrigin;
let nuxtOutput = "";
let statsAvailable = true;
const recordRequests = { manifest: 0, rows: 0 };

const shootingsManifest = {
  years_meta: {
    2022: {
      rows: 3,
      rows_url: "/shootings/rows/ssr-test-version/2022.ndjson",
    },
    2023: {
      rows: 2,
      rows_url: "/shootings/rows/ssr-test-version/2023.ndjson",
    },
  },
};

const shootingRowsByYear = {
  2022: [
    { fatal: true, lat: 39.95, lon: -75.16, marker: "ssr-record-marker" },
    { fatal: false, lat: 39.96, lon: -75.17 },
    { fatal: false, lat: null, lon: null },
  ],
  2023: [
    { fatal: true, lat: 39.95, lon: -75.16, marker: "ssr-record-marker" },
    { fatal: false, lat: 39.96, lon: -75.17 },
  ],
};

function resetRecordRequests() {
  recordRequests.manifest = 0;
  recordRequests.rows = 0;
}

function listen(server) {
  return new Promise((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolveListen(server.address().port);
    });
  });
}

async function findOpenPort() {
  const server = createServer();
  const port = await listen(server);
  await new Promise((resolveClose, reject) =>
    server.close((error) => (error ? reject(error) : resolveClose())),
  );
  return port;
}

async function waitForNuxt(
  url,
  processInstance = nuxtProcess,
  processOutput = () => nuxtOutput,
) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (processInstance.exitCode !== null) {
      throw new Error(`Nuxt exited before becoming ready.\n${processOutput()}`);
    }
    try {
      const response = await fetch(url);
      if (response.status < 500) return;
    } catch {
      // The server is still starting.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error(`Nuxt did not become ready.\n${processOutput()}`);
}

async function fetchDocument(path) {
  const url = new URL(path, nuxtOrigin);
  const response = await fetch(url);
  const html = await response.text();
  const dom = new JSDOM(html, { url });

  return { response, html, dom, document: dom.window.document };
}

async function startIsolatedNuxt(downloadsBaseUrl, readyRoute = "data") {
  const port = await findOpenPort();
  const origin = `http://127.0.0.1:${port}`;
  let output = "";
  const processInstance = spawn(process.execPath, [".output/server/index.mjs"], {
    cwd: frontendDirectory,
    env: {
      ...process.env,
      NITRO_HOST: "127.0.0.1",
      NITRO_PORT: String(port),
      NUXT_PUBLIC_API_BASE_URL: apiOrigin,
      NUXT_PUBLIC_DOWNLOADS_BASE_URL: downloadsBaseUrl,
      NUXT_PUBLIC_SITE_URL: "https://www.nickhand.dev",
      NUXT_PUBLIC_CANONICAL_BASE_URL: canonicalBase,
      NUXT_APP_BASE_URL: basePath,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  processInstance.stdout.on("data", (chunk) => {
    output += chunk;
  });
  processInstance.stderr.on("data", (chunk) => {
    output += chunk;
  });

  await waitForNuxt(
    `${origin}${basePath}${readyRoute}`,
    processInstance,
    () => output,
  );
  return { origin, processInstance };
}

function normalizedText(node) {
  return (node?.textContent ?? "").replace(/\s+/g, " ").trim();
}

function fixtureSizeLabel(bytes) {
  if (bytes < 1_000) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1_000;
  let unitIndex = 0;
  while (value >= 1_000 && unitIndex < units.length - 1) {
    value /= 1_000;
    unitIndex += 1;
  }
  return `${new Intl.NumberFormat("en-US", {
    maximumFractionDigits: value < 10 ? 1 : 0,
  }).format(value)} ${units[unitIndex]}`;
}

function assertVisibleAbbreviationDefinition(root, fullName, abbreviation) {
  const text = normalizedText(root);
  const definition = `${fullName} (${abbreviation})`;
  const definitionIndex = text.indexOf(definition);
  const firstAbbreviationIndex = text.search(
    new RegExp(`\\b${abbreviation}\\b`),
  );

  assert.notEqual(
    definitionIndex,
    -1,
    `Expected visible definition \"${definition}\"`,
  );
  assert.equal(
    firstAbbreviationIndex,
    definitionIndex + fullName.length + 2,
    `Expected ${abbreviation} to be defined before any later use`,
  );
}

function annualCountsTables(root) {
  return [...root.querySelectorAll("table")].filter((table) => {
    const headings = [...table.querySelectorAll('thead th[scope="col"]')].map(
      normalizedText,
    );
    return (
      headings.length === 3 &&
      headings[0] === "Year" &&
      headings[1] === "Shooting victims" &&
      headings[2] === "PPD homicides"
    );
  });
}

function annualRowForYear(table, year) {
  return [...table.querySelectorAll("tbody tr")].find((row) =>
    new RegExp(`^${year}\\b`).test(
      normalizedText(row.querySelector('th[scope="row"]')),
    ),
  );
}

function annualSourceLines(table) {
  const section = table.closest("section");
  return [...(section?.querySelectorAll("p") ?? [])].filter((paragraph) =>
    Boolean(paragraph.querySelector('a[rel~="external"]')),
  );
}

function dashboardSummaries(document) {
  return [...document.querySelectorAll(".civic-legacy-dashboard-header__summary")]
    .map(normalizedText);
}

function staticJavaScriptImports(source) {
  const imports = new Set();
  const patterns = [
    /\bfrom\s*["']([^"']+\.js)["']/g,
    /\bimport\s*["']([^"']+\.js)["']/g,
  ];

  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) imports.add(match[1]);
  }

  return imports;
}

async function collectInitialAssets(document) {
  const pending = [
    ...document.querySelectorAll('script[src], link[rel="modulepreload"][href]'),
  ].map((element) =>
    new URL(element.getAttribute("src") ?? element.getAttribute("href"), nuxtOrigin),
  );
  const stylesheets = [...document.querySelectorAll('link[rel="stylesheet"][href]')]
    .map((element) => new URL(element.getAttribute("href"), nuxtOrigin))
    .filter((url) => url.origin === nuxtOrigin);
  const assets = new Map();

  while (pending.length > 0) {
    const url = pending.pop();
    if (
      !url ||
      url.origin !== nuxtOrigin ||
      assets.has(url.href) ||
      !url.pathname.startsWith(`${basePath}_nuxt/`)
    ) {
      continue;
    }

    const response = await fetch(url);
    assert.equal(response.status, 200, `Unable to load initial asset ${url.pathname}`);
    const source = await response.text();
    assets.set(url.href, source);

    for (const importedPath of staticJavaScriptImports(source)) {
      pending.push(new URL(importedPath, url));
    }
  }

  for (const url of stylesheets) {
    if (!url.pathname.startsWith(`${basePath}_nuxt/`) || assets.has(url.href)) {
      continue;
    }
    const response = await fetch(url);
    assert.equal(response.status, 200, `Unable to load initial asset ${url.pathname}`);
    assets.set(url.href, await response.text());
  }

  return assets;
}

before(async () => {
  apiServer = createServer((request, response) => {
    if (request.url === "/shootings/meta") {
      recordRequests.manifest += 1;
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify(shootingsManifest));
      return;
    }

    const rowsMatch = request.url?.match(
      /^\/shootings\/rows\/ssr-test-version\/(2022|2023)\.ndjson$/,
    );
    if (rowsMatch) {
      recordRequests.rows += 1;
      const year = Number(rowsMatch[1]);
      response.writeHead(200, {
        "Content-Type": "application/x-ndjson",
      });
      response.end(
        shootingRowsByYear[year].map((row) => JSON.stringify(row)).join("\n"),
      );
      return;
    }

    if (request.url === "/stats.json" && !statsAvailable) {
      response.writeHead(503, { "Content-Type": "application/json" });
      response.end('{"detail":"Temporarily unavailable"}');
      return;
    }

    const payload =
      request.url === "/meta"
        ? meta
        : request.url === "/stats.json"
          ? stats
          : null;

    if (!payload) {
      response.writeHead(404, { "Content-Type": "application/json" });
      response.end('{"detail":"Not found"}');
      return;
    }

    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify(payload));
  });
  const apiPort = await listen(apiServer);
  apiOrigin = `http://127.0.0.1:${apiPort}`;

  downloadsServer = createServer((request, response) => {
    if (request.url === `${downloadsBasePath}/manifest.json`) {
      manifestRequestUserAgents.push(request.headers["user-agent"]);
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify(publicDownloadManifest));
      return;
    }
    if (request.url === `${slowDownloadsBasePath}/manifest.json`) {
      manifestRequestUserAgents.push(request.headers["user-agent"]);
      setTimeout(() => {
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(JSON.stringify(publicDownloadManifest));
      }, slowManifestDelayMs);
      return;
    }
    if (request.url === "/legacy-manifest/manifest.json") {
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify(legacyPublicDownloadManifest));
      return;
    }

    response.writeHead(404, { "Content-Type": "application/json" });
    response.end('{"detail":"Not found"}');
  });
  const downloadsPort = await listen(downloadsServer);
  downloadsOrigin = `http://127.0.0.1:${downloadsPort}`;
  downloadsBase = `${downloadsOrigin}${downloadsBasePath}`;
  allRecordsDownloadUrl =
    `${downloadsBase}/${publicDownloadReleasePrefix}/philadelphia-shooting-victims.csv`;

  const nuxtPort = await findOpenPort();
  nuxtOrigin = `http://127.0.0.1:${nuxtPort}`;

  nuxtProcess = spawn(process.execPath, [".output/server/index.mjs"], {
    cwd: frontendDirectory,
    env: {
      ...process.env,
      NITRO_HOST: "127.0.0.1",
      NITRO_PORT: String(nuxtPort),
      NUXT_PUBLIC_API_BASE_URL: apiOrigin,
      NUXT_PUBLIC_DOWNLOADS_BASE_URL: downloadsBase,
      NUXT_PUBLIC_SITE_URL: "https://www.nickhand.dev",
      NUXT_PUBLIC_CANONICAL_BASE_URL: canonicalBase,
      NUXT_APP_BASE_URL: basePath,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  nuxtProcess.stdout.on("data", (chunk) => {
    nuxtOutput += chunk;
  });
  nuxtProcess.stderr.on("data", (chunk) => {
    nuxtOutput += chunk;
  });

  await waitForNuxt(`${nuxtOrigin}${basePath}about`);
});

after(async () => {
  if (nuxtProcess?.exitCode === null) {
    nuxtProcess.kill("SIGTERM");
    await once(nuxtProcess, "exit");
  }
  if (apiServer?.listening) {
    await new Promise((resolveClose, reject) =>
      apiServer.close((error) => (error ? reject(error) : resolveClose())),
    );
  }
  if (downloadsServer?.listening) {
    await new Promise((resolveClose, reject) =>
      downloadsServer.close((error) =>
        error ? reject(error) : resolveClose(),
      ),
    );
  }
});

const pages = [
  {
    route: "about",
    h1: "About this dashboard",
    marker: "Status and stewardship",
  },
  {
    route: "stats",
    h1: "Philadelphia shooting-victim and homicide statistics",
    marker: "Current totals",
  },
  {
    route: "methodology",
    h1: "Methodology",
    marker: "Important transformations",
  },
  {
    route: "data",
    h1: "Data and downloads",
    marker: "About the records",
  },
];

test("dashboard root renders a complete, accessible SSR shell", async () => {
  resetRecordRequests();
  const { response, html, dom, document } = await fetchDocument(basePath);

  try {
    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type") ?? "", /^text\/html/);
    assert.equal(
      response.headers.get("strict-transport-security"),
      "max-age=31536000",
    );
    assert.equal(document.querySelectorAll("main").length, 1);
    assert.equal(document.querySelectorAll("h1").length, 1);
    assert.equal(
      document.querySelector("main")?.getAttribute("id"),
      "main-content",
    );
    assert.equal(document.querySelector("main")?.getAttribute("tabindex"), "-1");
    assert.equal(
      document.querySelector("h1")?.textContent?.trim(),
      "Mapping Philadelphia's Gun Violence",
    );
    assert.equal(
      normalizedText(document.querySelector(".civic-site-header__brand")),
      "Philadelphia Gun Violence Dashboard",
    );
    assert.doesNotMatch(html, /Independent civic data|Built in Wissahickon/i);
    assert.deepEqual(
      [...document.querySelectorAll(".civic-site-footer__links a")].map(
        normalizedText,
      ),
      ["Data sources", "Methodology", "Corrections", "Source code"],
    );
    assert.equal(
      document.querySelector("#explorer")?.getAttribute("aria-label"),
      "Explore the record",
    );

    const summaries = dashboardSummaries(document);
    assert.equal(summaries.length, 2);
    assert.match(
      summaries[0],
      /There have been 80 homicides in 2023,\s*a decrease of 20% from 2022\s*\./,
    );
    assert.match(
      summaries[1],
      /This map shows the victims of gun violence: 1 nonfatal and 1 fatal shooting victims so far in 2023\s*\./,
    );
    const clientFallback = document.querySelector(
      ".civic-legacy-map-explorer--fallback",
    );
    assert.match(normalizedText(clientFallback), /Loading interactive map and filters…/);
    assert.match(normalizedText(clientFallback), /Loading filters…/);
    assert.match(
      normalizedText(clientFallback),
      /Explore shooting-victim records on a map.*maps available locations.*filter records/i,
    );
    assert.equal(
      clientFallback?.querySelector(".civic-legacy-map-view a")?.getAttribute("href"),
      `${basePath}data`,
    );
    assert.equal(document.querySelector(".civic-dashboard-browser-explorer"), null);

    assert.equal(
      document.querySelector("title")?.textContent?.trim(),
      "Philadelphia Gun Violence Dashboard | Interactive Shootings Map & Data",
    );
    assert.match(
      document.querySelector('meta[name="description"]')?.getAttribute("content") ?? "",
      /explore 2 Philadelphia shooting-victim records in 2023/i,
    );
    assert.equal(document.querySelectorAll('link[rel="canonical"]').length, 1);
    assert.equal(
      document.querySelector('link[rel="canonical"]')?.getAttribute("href"),
      canonicalBase,
    );
    assert.equal(
      document.querySelector('meta[property="og:url"]')?.getAttribute("content"),
      canonicalBase,
    );
    assert.ok(
      !document
        .querySelector('meta[name="robots"]')
        ?.getAttribute("content")
        ?.includes("noindex"),
    );

    const structuredData = [...document.querySelectorAll('script[type="application/ld+json"]')]
      .map((script) => JSON.parse(script.textContent ?? "{}"))
      .find((value) => value["@type"] === "WebPage");
    assert.equal(structuredData?.url, canonicalBase);
    assert.equal("dateModified" in structuredData, false);

    const skipLink = document.querySelector('a[href="#main-content"]');
    assert.equal(skipLink?.textContent?.trim(), "Skip to main content");
    assert.equal(
      document.querySelector('nav[aria-label="Primary navigation"] a[aria-current="page"]')
        ?.textContent?.trim(),
      "Explore",
    );

    const form = document.querySelector(".civic-legacy-year-bar form");
    const label = document.querySelector('label[for="dashboard-year"]');
    const select = document.querySelector('select[name="year"]');
    const submit = form?.querySelector('button[type="submit"]');
    assert.ok(form);
    assert.equal(form.getAttribute("method")?.toLowerCase(), "get");
    assert.equal(form.getAttribute("action"), null);
    assert.equal(label?.textContent?.trim(), "Viewing data for");
    assert.equal(select?.getAttribute("id"), "dashboard-year");
    assert.equal(select?.disabled, false);
    assert.equal(document.querySelector('select[name="outcome"]'), null);
    assert.equal(document.querySelector('select[name="layers"]'), null);
    assert.equal(submit?.textContent?.trim(), "View year");
    assert.equal(submit?.disabled, false);
    assert.equal(select?.closest("button, a"), null);
    assert.equal(
      document.querySelectorAll("button button, button a, a button, a input, a select")
        .length,
      0,
    );

    const options = [...select.options];
    assert.equal(options.filter((option) => option.value === "All Years").length, 1);
    assert.deepEqual(
      options
        .filter((option) => option.value !== "All Years")
        .map((option) => option.value),
      ["2023", "2022"],
    );
    assert.equal(select.value, "2023");

    for (const route of ["stats", "data", "methodology"]) {
      assert.ok(
        document.querySelector(`a[href="${basePath}${route}"]`),
        `Missing dashboard link to ${route}`,
      );
    }
    for (const link of document.querySelectorAll('a[href^="/"]')) {
      assert.ok(
        link.getAttribute("href")?.startsWith(basePath),
        `Unprefixed internal link on dashboard: ${link.getAttribute("href")}`,
      );
    }

    assert.ok(!html.includes("<!-- __SEO_SUMMARY__ -->"));
    assert.ok(!html.includes("clip:rect"));
    assert.ok(!html.includes("ssr-record-marker"));
    assert.ok(!html.includes("/shootings/rows/ssr-test-version/"));
    assert.equal(document.querySelector(".civic-legacy-sidebar__section"), null);
    assert.deepEqual(recordRequests, { manifest: 0, rows: 0 });
  } finally {
    dom.window.close();
  }
});

test("dashboard year query drives truthful SSR summaries and a client loading shell", async () => {
  resetRecordRequests();
  const cases = [
    {
      homicide:
        /There have been 80 homicides in 2023,\s*a decrease of 20% from 2022\s*\./,
      query: "",
      selected: "2023",
      shooting:
        /This map shows the victims of gun violence: 1 nonfatal and 1 fatal shooting victims so far in 2023\s*\./,
    },
    {
      homicide: /In total, there were 500 homicides in 2022\s*\./,
      query: "?year=2022&outcome=nonfatal",
      selected: "2022",
      shooting: null,
    },
    {
      homicide: /There have been 580 homicides since 2022\s*\./,
      query: "?year=All%20Years&outcome=fatal&layers=heat-map",
      selected: "All Years",
      shooting: null,
    },
    {
      homicide:
        /There have been 80 homicides in 2023,\s*a decrease of 20% from 2022\s*\./,
      query: "?year=not-a-year&outcome=unknown&layers=unknown",
      selected: "2023",
      shooting:
        /This map shows the victims of gun violence: 1 nonfatal and 1 fatal shooting victims so far in 2023\s*\./,
    },
    {
      homicide:
        /There have been 80 homicides in 2023,\s*a decrease of 20% from 2022\s*\./,
      query:
        "?year=1999&outcome=fatal&outcome=nonfatal&layers=heat-map&layers=point-locations",
      selected: "2023",
      shooting:
        /This map shows the victims of gun violence: 1 nonfatal and 1 fatal shooting victims so far in 2023\s*\./,
    },
    {
      homicide:
        /There have been 80 homicides in 2023,\s*a decrease of 20% from 2022\s*\./,
      query: "?year=2022&year=2023",
      selected: "2023",
      shooting:
        /This map shows the victims of gun violence: 1 nonfatal and 1 fatal shooting victims so far in 2023\s*\./,
    },
    {
      homicide: /In total, there were 500 homicides in 2022\s*\./,
      query:
        "?year=2022&map=12%2F40%2F-75&map=13%2F40%2F-75",
      selected: "2022",
      shooting: null,
    },
  ];

  for (const item of cases) {
    const { response, dom, document } = await fetchDocument(`${basePath}${item.query}`);
    try {
      assert.equal(response.status, 200, `Unexpected status for ${item.query}`);
      assert.equal(document.querySelector('select[name="year"]')?.value, item.selected);
      assert.equal(
        document.querySelector("h1")?.textContent?.trim(),
        "Mapping Philadelphia's Gun Violence",
      );
      assert.equal(document.querySelector('select[name="outcome"]'), null);
      assert.equal(document.querySelector('select[name="layers"]'), null);
      assert.equal(
        document.querySelector('link[rel="canonical"]')?.getAttribute("href"),
        canonicalBase,
      );
      assert.equal(
        document.querySelector('meta[property="og:url"]')?.getAttribute("content"),
        canonicalBase,
      );
      const summaries = dashboardSummaries(document);
      assert.equal(summaries.length, 2);
      assert.match(summaries[0], item.homicide);
      if (item.shooting) {
        assert.match(summaries[1], item.shooting);
      } else {
        assert.equal(summaries[1], "");
      }
      const clientFallback = document.querySelector(
        ".civic-legacy-map-explorer--fallback",
      );
      assert.match(
        normalizedText(clientFallback),
        /Loading interactive map and filters…/,
      );
      assert.match(normalizedText(clientFallback), /Loading filters…/);
      assert.equal(document.querySelector(".civic-dashboard-browser-explorer"), null);
    } finally {
      dom.window.close();
    }
  }
  assert.deepEqual(recordRequests, { manifest: 0, rows: 0 });
});

test("dashboard year form works without JavaScript and preserves unrelated state", async () => {
  const mapView = "12.76/39.97240/-75.14142";
  const initialUrl = `${basePath}?year=2022&outcome=fatal&layers=point-locations&map=${encodeURIComponent(mapView)}`;
  const { dom, document } = await fetchDocument(initialUrl);
  let submittedUrl;

  try {
    const form = document.querySelector(".civic-legacy-year-bar form");
    const select = form?.querySelector('select[name="year"]');
    assert.ok(form);
    assert.ok(select);
    assert.equal(select.value, "2022");
    assert.equal(form?.querySelector('select[name="outcome"]'), null);
    assert.equal(form?.querySelector('select[name="layers"]'), null);
    select.value = "2023";

    const formData = new dom.window.FormData(form);
    const params = new URLSearchParams();
    for (const [name, value] of formData.entries()) {
      assert.equal(typeof value, "string");
      params.append(name, value);
    }
    submittedUrl = new URL(form.getAttribute("action") || dom.window.location.href);
    submittedUrl.search = params.toString();
  } finally {
    dom.window.close();
  }

  assert.equal(submittedUrl.pathname, basePath);
  assert.equal(submittedUrl.searchParams.get("year"), "2023");
  assert.equal(submittedUrl.searchParams.get("outcome"), "fatal");
  assert.equal(submittedUrl.searchParams.has("layers"), false);
  assert.equal(submittedUrl.searchParams.get("map"), mapView);
  assert.equal(submittedUrl.searchParams.getAll("year").length, 1);

  const { response, dom: submittedDom, document: submittedDocument } =
    await fetchDocument(submittedUrl.href);
  try {
    assert.equal(response.status, 200);
    assert.equal(
      submittedDocument.querySelector('select[name="year"]')?.value,
      "2023",
    );
    assert.equal(submittedDocument.querySelector('select[name="outcome"]'), null);
    assert.equal(submittedDocument.querySelector('select[name="layers"]'), null);
    const summaries = dashboardSummaries(submittedDocument);
    assert.match(
      summaries[0],
      /There have been 80 homicides in 2023,\s*a decrease of 20% from 2022\s*\./,
    );
    assert.match(
      summaries[1],
      /This map shows the victims of gun violence: 1 nonfatal and 1 fatal shooting victims so far in 2023\s*\./,
    );
    assert.equal(
      submittedDocument.querySelectorAll('form input[type="hidden"]').length,
      2,
    );
  } finally {
    submittedDom.window.close();
  }
});

test("dashboard renders an honest SSR fallback when statistics are unavailable", async () => {
  statsAvailable = false;
  try {
    const { response, dom, document } = await fetchDocument(
      `${basePath}?stats-unavailable=1`,
    );
    try {
      assert.equal(response.status, 200);
      assert.equal(
        document.querySelector("h1")?.textContent?.trim(),
        "Mapping Philadelphia's Gun Violence",
      );
      assert.match(
        dashboardSummaries(document)[0],
        /Homicide totals are temporarily unavailable\./,
      );
      assert.equal(dashboardSummaries(document)[1], "");
      assert.match(
        document.querySelector('p[role="status"].usa-sr-only')?.textContent ?? "",
        /Current totals could not be loaded\./,
      );
      assert.match(
        normalizedText(document.querySelector(".civic-legacy-map-explorer--fallback")),
        /Interactive records are temporarily unavailable\./,
      );
      assert.match(
        normalizedText(document.querySelector(".civic-legacy-map-explorer--fallback")),
        /Filters are unavailable while detailed records cannot be loaded\./,
      );

      const select = document.querySelector('select[name="year"]');
      const submit = document.querySelector(
        '.civic-legacy-year-bar form button[type="submit"]',
      );
      assert.equal(select?.disabled, true);
      assert.equal(select?.options.length, 1);
      assert.equal(select?.options[0]?.textContent?.trim(), "Years unavailable");
      assert.equal(document.querySelector('select[name="outcome"]'), null);
      assert.equal(document.querySelector('select[name="layers"]'), null);
      assert.equal(submit?.disabled, true);
      assert.equal(
        document.querySelector('link[rel="canonical"]')?.getAttribute("href"),
        canonicalBase,
      );

      for (const route of ["stats", "data", "methodology"]) {
        assert.ok(document.querySelector(`a[href="${basePath}${route}"]`));
      }
    } finally {
      dom.window.close();
    }
  } finally {
    statsAvailable = true;
  }
});

test("MapLibre is dynamically isolated and Nuxt emits no Vuetify code", async () => {
  const routePaths = [basePath, ...pages.map((page) => `${basePath}${page.route}`)];
  const initialAssets = new Map();
  const mapSignature = /maplibre(?:-gl|gl|-)?|mapbox-gl|maplibregl-/i;
  const vuetifySignature =
    /\bvuetify\b|\.v-application\b|\.v-btn\b|--v-theme-/i;

  for (const routePath of routePaths) {
    const { dom, document } = await fetchDocument(routePath);
    try {
      const assets = await collectInitialAssets(document);
      assert.ok(assets.size > 0, `Expected initial assets for ${routePath}`);
      for (const [url, source] of assets) {
        initialAssets.set(url, source);
        assert.doesNotMatch(
          source,
          mapSignature,
          `MapLibre found in the initial graph for ${routePath}: ${url}`,
        );
        assert.doesNotMatch(
          source,
          vuetifySignature,
          `Vuetify found in the initial graph for ${routePath}: ${url}`,
        );
      }
    } finally {
      dom.window.close();
    }
  }

  const assetDirectory = resolve(frontendDirectory, ".output/public/_nuxt");
  const emittedAssets = readdirSync(assetDirectory, { withFileTypes: true })
    .filter(
      (entry) =>
        entry.isFile() && (entry.name.endsWith(".js") || entry.name.endsWith(".css")),
    )
    .map((entry) => {
      const contents = readFileSync(join(assetDirectory, entry.name));
      return { contents, name: entry.name, source: contents.toString("utf8") };
    });

  for (const asset of emittedAssets) {
    assert.doesNotMatch(
      asset.source,
      vuetifySignature,
      `Vuetify found in emitted Nuxt asset ${asset.name}`,
    );
  }

  const mapAssets = emittedAssets.filter((asset) =>
    mapSignature.test(asset.source),
  );
  assert.ok(mapAssets.length > 0, "Expected a separately emitted MapLibre asset");
  const initialAssetNames = new Set(
    [...initialAssets.keys()].map((url) => new URL(url).pathname.split("/").at(-1)),
  );
  for (const asset of mapAssets) {
    assert.ok(
      !initialAssetNames.has(asset.name),
      `MapLibre asset was included in an initial route graph: ${asset.name}`,
    );
  }

  const mapJavaScriptGzip = mapAssets
    .filter((asset) => asset.name.endsWith(".js"))
    .reduce(
      (total, asset) => total + gzipSync(asset.contents, { level: 9 }).byteLength,
      0,
    );
  const mapCssGzip = mapAssets
    .filter((asset) => asset.name.endsWith(".css"))
    .reduce(
      (total, asset) => total + gzipSync(asset.contents, { level: 9 }).byteLength,
      0,
    );
  assert.ok(
    mapJavaScriptGzip <= 220 * 1024,
    `Dynamic map JavaScript is ${(mapJavaScriptGzip / 1024).toFixed(1)} KiB gzip`,
  );
  assert.ok(
    mapCssGzip <= 15 * 1024,
    `Dynamic map CSS is ${(mapCssGzip / 1024).toFixed(1)} KiB gzip`,
  );
});

test("stats raw SSR exposes sourced comparisons and one semantic annual counts table", async () => {
  const { response, dom, document } = await fetchDocument(`${basePath}stats`);

  try {
    assert.equal(response.status, 200);
    const main = document.querySelector("main#main-content");
    assert.ok(main);
    assert.equal(main.querySelectorAll("h1").length, 1);

    const current = main.querySelector(".civic-stats-current");
    assert.ok(current);
    const measures = [...current.querySelectorAll(".civic-current-measure")];
    assert.equal(measures.length, 2);
    const headedMeasures = measures.map((measure) => ({
      heading: measure.querySelector(":scope > h2, :scope > h3"),
      measure,
    }));
    assert.ok(headedMeasures.every(({ heading }) => Boolean(heading)));
    assert.equal(headedMeasures[0].heading.tagName, headedMeasures[1].heading.tagName);

    const shooting = headedMeasures.find(({ heading }) =>
      /shooting/i.test(normalizedText(heading)),
    )?.measure;
    const homicide = headedMeasures.find(({ heading }) =>
      /homicide/i.test(normalizedText(heading)),
    )?.measure;
    assert.ok(shooting);
    assert.ok(homicide);
    assert.equal(
      normalizedText(shooting.querySelector(":scope > h3")),
      "Shooting victims, 2023 to date",
    );
    assert.equal(
      normalizedText(homicide.querySelector(":scope > h3")),
      "PPD homicides, 2023 to date",
    );

    assert.equal(shooting.querySelectorAll(".civic-stat-total").length, 1);
    assert.equal(homicide.querySelectorAll(".civic-stat-total").length, 1);
    assert.equal(normalizedText(shooting.querySelector(".civic-stat-total")), "2");
    assert.equal(normalizedText(homicide.querySelector(".civic-stat-total")), "80");
    assert.equal(
      normalizedText(shooting.querySelector(".civic-outcome-list__fatal dd")),
      "1",
    );
    assert.equal(
      normalizedText(shooting.querySelector(".civic-outcome-list__nonfatal dd")),
      "1",
    );

    const shootingTotal = shooting.querySelector(":scope > .civic-stat-total");
    const homicideTotal = homicide.querySelector(":scope > .civic-stat-total");
    const shootingDate = shooting.querySelector(":scope > .civic-current-through");
    const homicideDate = homicide.querySelector(":scope > .civic-current-through");
    assert.ok(shootingDate);
    assert.ok(homicideDate);
    assert.equal(shootingTotal.nextElementSibling, shootingDate);
    assert.equal(homicideTotal.nextElementSibling, homicideDate);
    assert.equal(
      normalizedText(shootingDate),
      "Through January 15, 2023",
    );
    assert.equal(
      normalizedText(homicideDate),
      "Through January 16, 2023",
    );
    assert.equal(
      shootingDate.querySelector("time")?.getAttribute("datetime"),
      "2023-01-15",
    );
    assert.equal(
      homicideDate.querySelector("time")?.getAttribute("datetime"),
      "2023-01-16",
    );

    const comparisons = [
      { measure: shooting, change: /(?:up|increase|higher)/i, percent: "100%", previous: "1" },
      { measure: homicide, change: /(?:down|decrease|lower)/i, percent: "20%", previous: "100" },
    ];
    for (const comparison of comparisons) {
      const nodes = comparison.measure.querySelectorAll(".civic-current-comparison");
      assert.equal(nodes.length, 1);
      const text = normalizedText(nodes[0]);
      assert.match(text, comparison.change);
      assert.match(text, new RegExp(`\\b${comparison.percent.replace("%", "")}\\s*%`));
      assert.match(text, new RegExp(`\\b${comparison.previous}\\b`));
      assert.match(text, /same (?:point|period).*2022/i);
      assert.equal(
        comparison.measure.querySelector(":scope > .civic-current-through")
          ?.nextElementSibling,
        nodes[0],
      );
    }

    const shootingOutcome = shooting.querySelector(":scope > .civic-outcome-list");
    assert.ok(shootingOutcome);
    assert.equal(
      shooting.querySelector(":scope > .civic-current-comparison")
        ?.nextElementSibling,
      shootingOutcome,
    );
    assert.equal(homicide.querySelector(":scope > .civic-outcome-list"), null);

    assert.equal(current.querySelectorAll(".civic-current-source").length, 0);
    assert.equal(current.querySelectorAll(".civic-current-definition").length, 0);
    assert.equal(current.querySelectorAll(".civic-current-sources").length, 0);
    assert.equal(current.querySelectorAll('a[rel~="external"]').length, 0);
    const currentGrid = current.querySelector(":scope > .civic-stats-current__grid");
    const context = current.querySelector(":scope > .civic-current-context");
    assert.ok(currentGrid);
    assert.ok(context);
    assert.equal(currentGrid.nextElementSibling, context);
    assert.equal(context.nextElementSibling, null);
    assert.match(
      normalizedText(context),
      /all homicides citywide.*whether or not a gun was involved/i,
    );
    assert.match(
      normalizedText(context),
      /measures can overlap.*should not be added/i,
    );
    assert.equal(
      (normalizedText(main).match(/should not be added/gi) ?? []).length,
      1,
      "The overlap warning should appear once on the Statistics page",
    );
    const annualTables = annualCountsTables(main);
    assert.equal(annualTables.length, 1);
    const annualTable = annualTables[0];
    const annualSection = annualTable.closest("section");
    const annualTitleRow = annualSection?.querySelector(
      ".civic-annual-heading__title-row",
    );
    const annualHeading = annualTitleRow?.querySelector("#counts-by-year");
    const printButton = annualTitleRow?.querySelector(".civic-print-button");
    assert.ok(annualSection);
    assert.ok(annualTitleRow);
    assert.ok(annualHeading);
    assert.equal(normalizedText(annualHeading), "Counts by year");
    assert.ok(printButton);
    assert.equal(normalizedText(printButton), "Print counts by year");
    assert.equal(annualHeading.parentElement, annualTitleRow);
    assert.equal(printButton.parentElement, annualTitleRow);

    const annualCaption = normalizedText(annualTable.querySelector("caption"));
    assert.match(annualCaption, /shooting/i);
    assert.match(annualCaption, /homicide/i);
    assert.match(annualCaption, /annual|year/i);
    assert.equal(annualTable.querySelectorAll('tbody th[scope="row"]').length, 2);

    const expectedRows = [
      { year: 2022, victims: "3", homicides: "500" },
      { year: 2023, victims: "2", homicides: "80" },
    ];
    for (const expected of expectedRows) {
      const row = annualRowForYear(annualTable, expected.year);
      assert.ok(row);
      const cells = [...row.querySelectorAll("td")];
      assert.equal(cells.length, 2);
      assert.match(normalizedText(cells[0]), new RegExp(`^${expected.victims}(?:\\s|$)`));
      assert.match(normalizedText(cells[1]), new RegExp(`^${expected.homicides}(?:\\s|$)`));

      const shootingDecorations = cells[0].querySelectorAll('[aria-hidden="true"]');
      assert.ok(shootingDecorations.length > 0);
      assert.equal(cells[1].querySelectorAll('[aria-hidden="true"]').length, 0);
      for (const decoration of shootingDecorations) {
        assert.equal(normalizedText(decoration), "");
      }
    }

    const currentRow = annualRowForYear(annualTable, 2023);
    assert.match(normalizedText(currentRow), /2023\s+Year to date/i);
    assert.match(normalizedText(currentRow), /through January 15, 2023/i);
    assert.match(normalizedText(currentRow), /through January 16, 2023/i);
    const victimsCell = currentRow.querySelector("td.civic-annual-victims");
    const homicideCell = currentRow.querySelector("td.civic-annual-homicides");
    const annualVictimsDate = victimsCell?.querySelector(
      ".civic-annual-current-date--victims",
    );
    const annualHomicideDate = homicideCell?.querySelector(
      ".civic-annual-current-date--homicides",
    );
    assert.ok(victimsCell);
    assert.ok(homicideCell);
    assert.ok(annualVictimsDate);
    assert.ok(annualHomicideDate);
    assert.equal(annualVictimsDate.closest("td"), victimsCell);
    assert.equal(annualHomicideDate.closest("td"), homicideCell);
    assert.equal(
      annualVictimsDate.querySelector("time")?.getAttribute("datetime"),
      "2023-01-15",
    );
    assert.equal(
      annualHomicideDate.querySelector("time")?.getAttribute("datetime"),
      "2023-01-16",
    );

    const sources = annualSourceLines(annualTable);
    assert.equal(sources.length, 2);
    assert.equal(sources[0].nextElementSibling, sources[1]);
    assert.equal(
      annualSection.querySelectorAll(".civic-annual-sources a[rel~='external']")
        .length,
      2,
    );
    assert.match(
      normalizedText(sources[0]),
      /Shooting victims:.*Philadelphia Police Department shooting-victim records/i,
    );
    assert.match(
      normalizedText(sources[1]),
      /Homicides:.*Philadelphia Police Department homicide statistics/i,
    );
  } finally {
    dom.window.close();
  }
});

test("stats raw SSR distinguishes an exact tie from a rounded zero-percent change", async () => {
  const original = {
    homicides_previous_ytd: stats.homicides_previous_ytd,
    homicides_ytd: stats.homicides_ytd,
    homicide_percent_change: stats.homicide_percent_change,
    shooting_percent_change: stats.shooting_percent_change,
    shootings_previous_ytd: stats.shootings_previous_ytd,
  };
  Object.assign(stats, {
    homicides_previous_ytd: 500,
    homicides_ytd: 501,
    homicide_percent_change: 0,
    shooting_percent_change: 0,
    shootings_previous_ytd: stats.current_total,
  });

  let dom;
  try {
    const rendered = await fetchDocument(`${basePath}stats?comparison-case=tie`);
    dom = rendered.dom;
    const measures = [...rendered.document.querySelectorAll(".civic-current-measure")];
    const shooting = measures.find((measure) =>
      /shooting/i.test(normalizedText(measure.querySelector("h2, h3"))),
    );
    const homicide = measures.find((measure) =>
      /homicide/i.test(normalizedText(measure.querySelector("h2, h3"))),
    );
    const shootingComparison = normalizedText(
      shooting?.querySelector(".civic-current-comparison"),
    );
    const homicideComparison = normalizedText(
      homicide?.querySelector(".civic-current-comparison"),
    );

    assert.match(shootingComparison, /same (?:point|period).*2022/i);
    assert.match(shootingComparison, /\b2\b/);
    assert.match(shootingComparison, /no change/i);
    assert.match(homicideComparison, /same (?:point|period).*2022/i);
    assert.match(homicideComparison, /\b500\b/);
    assert.match(homicideComparison, /higher|increase|up/i);
    assert.doesNotMatch(homicideComparison, /no change/i);
  } finally {
    dom?.window.close();
    Object.assign(stats, original);
  }
});

test("content routes render complete, unique crawler responses", async () => {
  const titles = new Set();

  for (const page of pages) {
    const response = await fetch(`${nuxtOrigin}${basePath}${page.route}`);
    const html = await response.text();
    const document = new JSDOM(html).window.document;
    const canonical = `${canonicalBase}/${page.route}`;

    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type") ?? "", /^text\/html/);
    assert.equal(document.querySelectorAll("main").length, 1);
    assert.equal(document.querySelectorAll("h1").length, 1);
    assert.ok(document.querySelector("main")?.classList.contains("civic-reference-page"));
    assert.equal(document.querySelector("h1")?.textContent?.trim(), page.h1);
    assert.match(document.querySelector("main")?.textContent ?? "", new RegExp(page.marker));

    const canonicalLinks = document.querySelectorAll('link[rel="canonical"]');
    assert.equal(canonicalLinks.length, 1);
    assert.equal(canonicalLinks[0].getAttribute("href"), canonical);
    assert.equal(document.querySelector('meta[property="og:url"]')?.getAttribute("content"), canonical);

    const title = document.querySelector("title")?.textContent?.trim();
    const description = document
      .querySelector('meta[name="description"]')
      ?.getAttribute("content");
    assert.ok(title);
    assert.ok(description);
    assert.ok(!titles.has(title), `Duplicate page title: ${title}`);
    titles.add(title);

    const robots = document
      .querySelector('meta[name="robots"]')
      ?.getAttribute("content");
    assert.ok(!robots?.includes("noindex"));
    assert.ok(!html.includes("<!-- __SEO_SUMMARY__ -->"));
    assert.ok(!html.includes("clip:rect"));
    assert.ok(!html.toLowerCase().includes("maplibre"));

    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      assert.doesNotThrow(() => JSON.parse(script.textContent ?? ""));
    }

    if (page.route === "stats") {
      assertVisibleAbbreviationDefinition(
        document.querySelector("main"),
        "Philadelphia Police Department",
        "PPD",
      );
      assert.equal(document.querySelector(".civic-stat-total")?.textContent?.trim(), "2");
      assert.equal(
        document.querySelector(".civic-outcome-list__fatal dd")?.textContent?.trim(),
        "1",
      );
      assert.equal(
        document.querySelector(".civic-outcome-list__nonfatal dd")?.textContent?.trim(),
        "1",
      );
      assert.match(document.querySelector("main")?.textContent ?? "", /January 15, 2023/);
      assert.match(document.querySelector("main")?.textContent ?? "", /January 16, 2023/);

      const annualTables = annualCountsTables(document);
      assert.equal(annualTables.length, 1);
      const annualTable = annualTables[0];
      assert.doesNotMatch(document.querySelector("main")?.textContent ?? "", /Relative count/);

      const priorRow = annualRowForYear(annualTable, 2022);
      assert.ok(priorRow);
      const priorCells = [...priorRow.querySelectorAll("td")];
      assert.equal(normalizedText(priorCells[0]), "3");
      assert.equal(normalizedText(priorCells[1]), "500");
      assert.ok(priorCells[0].querySelector('[aria-hidden="true"]'));
      assert.equal(priorCells[1].querySelector('[aria-hidden="true"]'), null);

      const currentRow = annualRowForYear(annualTable, 2023);
      assert.ok(currentRow);
      const currentCells = [...currentRow.querySelectorAll("td")];
      assert.match(normalizedText(currentCells[0]), /^2(?:\s|$)/);
      assert.match(normalizedText(currentCells[1]), /^80(?:\s|$)/);
      assert.ok(currentCells[0].querySelector('[aria-hidden="true"]'));
      assert.equal(currentCells[1].querySelector('[aria-hidden="true"]'), null);
      assert.match(normalizedText(currentRow), /2023\s+Year to date/i);
      assert.match(normalizedText(currentRow), /through January 15, 2023/i);
      assert.match(normalizedText(currentRow), /through January 16, 2023/i);

      const annualSources = annualSourceLines(annualTable);
      assert.equal(annualSources.length, 2);
      assert.equal(annualSources[0].nextElementSibling, annualSources[1]);
      assert.match(
        normalizedText(annualSources[0]),
        /Shooting victims:.*Philadelphia Police Department shooting-victim records/i,
      );
      assert.match(
        normalizedText(annualSources[1]),
        /Homicides:.*Philadelphia Police Department homicide statistics/i,
      );
      const printButton = [...document.querySelectorAll("button")].find(
        (button) => normalizedText(button) === "Print counts by year",
      );
      assert.ok(printButton);

      const structuredData = [...document.querySelectorAll('script[type="application/ld+json"]')]
        .map((script) => JSON.parse(script.textContent ?? "{}"))
        .find((value) => Array.isArray(value["@graph"]));
      const webPage = structuredData?.["@graph"].find(
        (entry) => entry["@type"] === "WebPage",
      );
      const dataset = structuredData?.["@graph"].find(
        (entry) => entry["@type"] === "Dataset",
      );
      assert.equal("dateModified" in webPage, false);
      assert.equal("dateModified" in dataset, false);
      assert.equal(
        dataset?.name,
        "Philadelphia shooting-victim and homicide statistics",
      );
      assert.deepEqual(dataset?.isBasedOn, [
        "https://opendataphilly.org/datasets/shooting-victims/",
        "https://www.phillypolice.com/crime-data/crime-statistics/",
      ]);
      assert.equal("distribution" in dataset, false);
    }

    if (page.route === "about") {
      const main = document.querySelector("main");
      const corrections = document.querySelector(
        '[aria-labelledby="corrections"]',
      );
      const maintainerLink = [...document.querySelectorAll("main a[href]")].find(
        (link) => normalizedText(link) === "Nick Hand",
      );
      const correctionIssueLink = document.querySelector(
        'main a[href="https://github.com/nickhand/philly-gun-violence-dashboard/issues/new"]',
      );

      assertVisibleAbbreviationDefinition(
        main,
        "Philadelphia Police Department",
        "PPD",
      );
      assert.equal(document.querySelectorAll(".usa-summary-box").length, 0);
      assert.equal(document.querySelectorAll(".usa-button-group").length, 0);
      assert.match(
        main?.textContent ?? "",
        /one person reported shot, not one shooting incident/,
      );
      assert.match(
        normalizedText(main),
        /all homicides citywide.*whether or not a gun was involved/i,
      );
      assert.equal(
        (main?.textContent ?? "").match(
          /not an official City of Philadelphia website/g,
        )?.length,
        1,
      );
      assert.equal(maintainerLink?.getAttribute("href"), "https://www.nickhand.dev/");
      assert.ok(correctionIssueLink, "Expected corrections to link directly to a new GitHub issue");
      assert.equal(document.querySelectorAll('main a[href^="mailto:"]').length, 0);
      assert.match(normalizedText(corrections), /GitHub issues are public/i);
      assert.match(
        normalizedText(corrections),
        /do not include sensitive personal information/i,
      );
    }

    if (page.route === "data") {
      assertVisibleAbbreviationDefinition(
        document.querySelector("main"),
        "Philadelphia Police Department",
        "PPD",
      );
      assert.equal(document.querySelectorAll(".civic-dashboard-download").length, 0);
      const mainText = normalizedText(document.querySelector("main"));
      const intro = document.querySelector(".civic-page-intro .usa-intro");
      const aboutRecords = document.querySelector(
        '[aria-labelledby="about-records"]',
      );
      const downloadGuide = document.querySelector(
        '[aria-labelledby="explore-download"]',
      );
      const sourceRecords = document.querySelector(
        '[aria-labelledby="source-records"]',
      );
      const considerations = document.querySelector(
        '[aria-labelledby="using-records"]',
      );
      const citation = document.querySelector(
        '[aria-labelledby="cite-dashboard"]',
      );
      const geographicReferences = document.querySelector(
        '[aria-labelledby="geographic-reference-downloads"]',
      );
      const shootingSourceRow = sourceRecords?.querySelector("tbody tr");
      const homicideSourceRow = sourceRecords?.querySelectorAll("tbody tr")[1];
      const allRecordsDownload = downloadGuide?.querySelector(
        `a[href="${allRecordsDownloadUrl}"]`,
      );
      const allRecordsDescription = document.querySelector(
        "#all-records-download-description",
      );

      assert.match(
        normalizedText(intro),
        /latest date included|when the records were last updated/i,
      );
      assert.match(
        normalizedText(aboutRecords),
        /Each row represents one person.*PPD.*shooting victim/i,
      );
      assert.match(
        normalizedText(aboutRecords),
        /one incident can have more than one row/i,
      );
      assert.match(
        normalizedText(aboutRecords),
        /does not include.*officer-involved/i,
      );
      assert.match(
        normalizedText(aboutRecords),
        /latest data.*through January 15, 2023/i,
      );
      assert.match(
        normalizedText(aboutRecords),
        /shooting-victim records only.*do not include.*citywide homicide totals/i,
      );
      assert.ok(
        allRecordsDownload,
        "Expected the configured all-records CSV link in server-rendered HTML",
      );
      assert.ok(allRecordsDownload.classList.contains("civic-file-download-link"));
      assert.ok(allRecordsDownload.classList.contains("usa-button"));
      assert.equal(
        normalizedText(
          allRecordsDownload.querySelector(".civic-file-download-link__label"),
        ),
        "Download all shooting-victim records",
      );
      assert.equal(
        normalizedText(
          allRecordsDownload.querySelector(".civic-file-download-link__metadata"),
        ),
        "[CSV, 3.1 MB]",
      );
      assert.equal(
        allRecordsDownload.querySelector("svg.civic-icon")?.getAttribute(
          "aria-hidden",
        ),
        "true",
      );
      assert.equal(
        allRecordsDownload.querySelector("svg.civic-icon")?.getAttribute(
          "focusable",
        ),
        "false",
      );
      assert.equal(
        allRecordsDownload.getAttribute("aria-describedby"),
        "all-records-download-description",
      );
      assert.match(
        normalizedText(allRecordsDescription),
        /every available year.*one row for each person/i,
      );
      assert.match(
        normalizedText(allRecordsDescription),
        /5 records through January 15, 2023/i,
      );
      const directCsvLinks = [...downloadGuide.querySelectorAll('a[href$=".csv"]')];
      assert.deepEqual(
        directCsvLinks.map((link) => link.getAttribute("href")),
        [allRecordsDownloadUrl],
        "The data page should provide one clear all-years CSV link, not a list by year",
      );
      const publicDownloadUrl = new URL(allRecordsDownload.getAttribute("href"));
      assert.equal(publicDownloadUrl.origin, downloadsOrigin);
      assert.equal(publicDownloadUrl.href.startsWith(`${downloadsBase}/`), true);
      assert.doesNotMatch(
        publicDownloadUrl.href,
        /philly-gun-violence-dashboard-api\.fly\.dev|\/(?:shootings|stats\.json|meta|openapi(?:\.json)?|docs)(?:[/?#]|$)/i,
      );
      assert.match(normalizedText(downloadGuide), /filters/i);
      assert.match(normalizedText(downloadGuide), /CSV.*GeoJSON/i);
      assert.match(normalizedText(downloadGuide), /Aggregate By/i);
      assert.equal(
        normalizedText(sourceRecords?.querySelector("h2")),
        "Sources and dates",
      );
      assert.match(
        normalizedText(sourceRecords),
        /latest incident date.*does not mean.*every incident.*may add or change records later/i,
      );
      assert.match(
        normalizedText(sourceRecords),
        /checks PPD shooting-victim and homicide sources each day.*may not post new data on weekends or holidays.*UJS court records runs once a week/i,
      );
      assert.match(
        normalizedText(shootingSourceRow),
        /Records through January 15, 2023.*Dashboard updated January 16, 2023/i,
      );
      assert.match(
        normalizedText(homicideSourceRow),
        /all homicides citywide.*whether or not a gun was involved/i,
      );
      assert.match(
        normalizedText(considerations),
        /without usable coordinates remain in totals and downloads/i,
      );
      assert.match(
        normalizedText(considerations),
        /court-search flag.*does not prove.*charged.*case ended.*relates to a victim/i,
      );
      assert.equal(
        normalizedText(geographicReferences?.querySelector("h3")),
        "Download map reference files",
      );
      assert.match(
        normalizedText(geographicReferences),
        /GeoJSON.*match the field.*join.*not historical boundary files.*segment_id.*may change/i,
      );
      const referenceRows = [
        ...(geographicReferences?.querySelectorAll("tbody tr") ?? []),
      ];
      assert.equal(referenceRows.length, geographicReferenceDownloads.length);
      for (const [index, [label, joinField, filename, byteSize]] of
        geographicReferenceDownloads.entries()) {
        const row = referenceRows[index];
        const link = row?.querySelector("a");
        assert.equal(
          normalizedText(
            link?.querySelector(".civic-file-download-link__label"),
          ),
          `Download ${label}`,
        );
        assert.equal(
          normalizedText(
            link?.querySelector(".civic-file-download-link__metadata"),
          ),
          `[GEOJSON, ${fixtureSizeLabel(byteSize)}]`,
        );
        assert.equal(
          link?.querySelector("svg.civic-icon")?.getAttribute("aria-hidden"),
          "true",
        );
        assert.equal(
          link?.querySelector("svg.civic-icon")?.getAttribute("focusable"),
          "false",
        );
        assert.equal(
          link?.getAttribute("href"),
          `${downloadsBase}/${publicDownloadReleasePrefix}/geography/${filename}`,
        );
        assert.equal(link?.getAttribute("download"), filename);
        assert.equal(link?.getAttribute("type"), "application/geo+json");
        assert.equal(normalizedText(row?.querySelector("code")), joinField);
      }
      assert.equal(
        normalizedText(citation?.querySelector("h2")),
        "Citing this dashboard",
      );
      assert.match(
        normalizedText(citation),
        /include the Philadelphia Gun Violence Dashboard.*measure and time period.*records through.*date you accessed.*page URL/i,
      );
      assert.match(
        normalizedText(citation),
        /Philadelphia Gun Violence Dashboard.*Data and downloads.*Shooting-victim records through January 15, 2023.*Philadelphia Police Department via OpenDataPhilly.*Accessed [A-Z][a-z]+ \d{1,2}, \d{4}/i,
      );
      const citationBlock = citation?.querySelector("blockquote");
      assert.ok(citationBlock, "Expected the citation in a semantic blockquote");
      assert.equal(
        citationBlock?.getAttribute("cite"),
        `${canonicalBase}/data`,
      );
      assert.doesNotMatch(normalizedText(citationBlock), /\bExample:/i);
      const copyCitationButton = citation?.querySelector(
        'button[type="button"]',
      );
      assert.equal(normalizedText(copyCitationButton), "Copy citation");
      assert.equal(
        copyCitationButton?.nextElementSibling?.getAttribute("role"),
        "status",
      );
      assert.equal(
        citationBlock?.querySelector("a")?.getAttribute("href"),
        `${canonicalBase}/data`,
      );
      assert.doesNotMatch(
        mainText,
        /\bAPI\b|NDJSON|data manifest|API routes/i,
      );
      assert.doesNotMatch(
        mainText,
        /\bfreshness\b|current dashboard copy/i,
      );

      const structuredData = [...document.querySelectorAll('script[type="application/ld+json"]')]
        .map((script) => JSON.parse(script.textContent ?? "{}"))
        .find((value) => Array.isArray(value["@graph"]));
      const dataset = structuredData?.["@graph"].find(
        (entry) => entry["@id"] === `${canonicalBase}/data#dataset`,
      );
      const geographicDataset = structuredData?.["@graph"].find(
        (entry) =>
          entry["@id"] === `${canonicalBase}/data#geographic-reference-data`,
      );
      assert.equal(dataset?.dateModified, "2023-01-16T08:00:00Z");
      assert.equal(dataset?.temporalCoverage, "2015-01-01/2023-01-15");
      assert.match(dataset?.description ?? "", /Each row represents one person/i);
      assert.match(
        dataset?.description ?? "",
        /does not include.*officer-involved/i,
      );
      assert.equal(dataset?.distribution?.["@type"], "DataDownload");
      assert.equal(
        dataset?.distribution?.name,
        "All Philadelphia shooting-victim records",
      );
      assert.equal(dataset?.distribution?.contentUrl, allRecordsDownloadUrl);
      assert.equal(dataset?.distribution?.contentSize, "3064024 bytes");
      assert.equal(dataset?.distribution?.encodingFormat, "text/csv");
      assert.match(
        dataset?.distribution?.description ?? "",
        /every available year.*one row for each person/i,
      );
      assert.doesNotMatch(dataset?.distribution?.description ?? "", /<[^>]+>/);
      assert.equal(geographicDataset?.["@type"], "Dataset");
      assert.equal(geographicDataset?.distribution?.length, 8);
      assert.deepEqual(
        geographicDataset.distribution.map((item) => item.contentUrl),
        geographicReferenceDownloads.map(
          ([, , filename]) =>
            `${downloadsBase}/${publicDownloadReleasePrefix}/geography/${filename}`,
        ),
      );
      assert.deepEqual(
        geographicDataset.distribution.map((item) => item.contentSize),
        geographicReferenceDownloads.map(
          ([, , , byteSize]) => `${byteSize} bytes`,
        ),
      );
      assert.ok(
        geographicDataset.distribution.every(
          (item) => item.encodingFormat === "application/geo+json",
        ),
      );
    }

    if (page.route === "methodology") {
      const processList = document.querySelector(
        '[aria-labelledby="pipeline"] > .usa-process-list',
      );
      assert.equal(processList?.tagName, "OL");
      assert.deepEqual(
        [...(processList?.querySelectorAll(".usa-process-list__heading") ?? [])].map(
          normalizedText,
        ),
        ["Collect", "Prepare", "Check", "Publish"],
      );
      assert.equal(document.querySelectorAll(".usa-step-indicator").length, 0);

      const structuredData = [...document.querySelectorAll('script[type="application/ld+json"]')]
        .map((script) => JSON.parse(script.textContent ?? "{}"))
        .find((value) => value["@type"] === "WebPage");
      assert.equal("dateModified" in structuredData, false);
      const mainText = normalizedText(document.querySelector("main"));
      const recordScope = document.querySelector(
        '[aria-labelledby="record-scope"]',
      );
      const courtSearchScope = recordScope?.querySelector("p:last-child");
      assert.match(
        normalizedText(recordScope),
        /One incident may produce several records.*officer-involved.*excluded/i,
      );
      assert.match(
        normalizedText(recordScope),
        /all homicides citywide.*whether or not a gun was involved.*separately from shooting-victim records/i,
      );
      assert.match(
        normalizedText(courtSearchScope),
        /police incident number.*automated search.*UJS.*public court portal.*records whether.*returned a result.*does not copy case details/i,
      );
      assert.match(mainText, /no maximum distance/i);
      assert.match(
        mainText,
        /do not explain causes.*should not be used to make claims about an individual/i,
      );
      assert.doesNotMatch(mainText, /begins with public|starts with public/i);
      assert.doesNotMatch(
        mainText,
        /\bAPI\b|NDJSON|data manifest|interactive API documentation/i,
      );
    }

    if (["data", "methodology", "stats"].includes(page.route)) {
      const endpointPattern =
        /philly-gun-violence-dashboard-api\.fly\.dev|\/shootings(?:[/?#]|$)|\/(?:stats\.json|openapi(?:\.json)?|docs|meta)(?:[?#/]|$)/i;
      for (const link of document.querySelectorAll("main a[href]")) {
        assert.doesNotMatch(
          link.getAttribute("href") ?? "",
          endpointPattern,
          `Internal endpoint exposed on ${page.route}`,
        );
      }
      const structuredDataText = [...document.querySelectorAll(
        'script[type="application/ld+json"]',
      )]
        .map((script) => script.textContent ?? "")
        .join("\n");
      assert.doesNotMatch(structuredDataText, endpointPattern);
      if (page.route === "data") {
        assert.equal(
          (structuredDataText.match(/"contentUrl"\s*:/gi) ?? []).length,
          9,
          "The Data page should advertise one CSV and eight geographic files",
        );
      } else {
        assert.doesNotMatch(structuredDataText, /"contentUrl"\s*:/i);
      }
    }

    for (const link of document.querySelectorAll('a[href^="/"]')) {
      assert.ok(
        link.getAttribute("href")?.startsWith(basePath),
        `Unprefixed internal link on ${page.route}: ${link.getAttribute("href")}`,
      );
    }
  }
});

test("robots policy is plain text and points to the canonical sitemap", async () => {
  const response = await fetch(`${nuxtOrigin}${basePath}robots.txt`);
  const body = await response.text();

  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/plain/);
  assert.match(body, /^User-agent: \*$/m);
  assert.match(body, /^Allow: \/$/m);
  assert.equal(
    body.match(/^Sitemap:/gm)?.length,
    1,
    "robots.txt should advertise one canonical sitemap",
  );
  assert.match(
    body,
    /^Sitemap: https:\/\/www\.nickhand\.dev\/philly-gun-violence-map\/sitemap\.xml$/m,
  );
  assert.ok(!body.toLowerCase().includes("<html"));
});

test("the public download manifest proxy returns the CDN contract without exposing its origin", async () => {
  manifestRequestUserAgents.length = 0;
  const response = await fetch(
    `${nuxtOrigin}${basePath}api/public-download-manifest`,
  );

  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /application\/json/);
  assert.equal(
    response.headers.get("cache-control"),
    "public, max-age=300, stale-while-revalidate=3600",
  );
  assert.deepEqual(await response.json(), publicDownloadManifest);
  assert.deepEqual(manifestRequestUserAgents, [
    "Philadelphia-Gun-Violence-Dashboard/1.0",
  ]);
});

test("a slow public download manifest still drives v2 Data page SSR", async () => {
  const slowDownloadsBase = `${downloadsOrigin}${slowDownloadsBasePath}`;
  const { origin, processInstance } = await startIsolatedNuxt(
    slowDownloadsBase,
    "about",
  );
  let dom;

  try {
    const manifestResponse = await fetch(
      `${origin}${basePath}api/public-download-manifest`,
    );
    assert.equal(manifestResponse.status, 200);
    assert.equal(
      manifestResponse.headers.get("cache-control"),
      "public, max-age=300, stale-while-revalidate=3600",
    );
    assert.deepEqual(await manifestResponse.json(), publicDownloadManifest);

    const dataResponse = await fetch(`${origin}${basePath}data`);
    const html = await dataResponse.text();
    dom = new JSDOM(html, { url: `${origin}${basePath}data` });
    const { document } = dom.window;
    const links = [
      ...document.querySelectorAll("main a.civic-file-download-link"),
    ];
    const expectedUrls = [
      `${slowDownloadsBase}/${publicDownloadReleasePrefix}/philadelphia-shooting-victims.csv`,
      ...geographicReferenceDownloads.map(
        ([, , filename]) =>
          `${slowDownloadsBase}/${publicDownloadReleasePrefix}/geography/${filename}`,
      ),
    ];
    const expectedMetadata = [
      "[CSV, 3.1 MB]",
      ...geographicReferenceDownloads.map(
        ([, , , byteSize]) => `[GEOJSON, ${fixtureSizeLabel(byteSize)}]`,
      ),
    ];

    assert.equal(dataResponse.status, 200);
    assert.deepEqual(
      links.map((link) => link.getAttribute("href")),
      expectedUrls,
      "SSR should use the immutable v2 release paths after a slow manifest response",
    );
    assert.deepEqual(
      links.map((link) =>
        normalizedText(
          link.querySelector(".civic-file-download-link__metadata"),
        ),
      ),
      expectedMetadata,
      "SSR should use byte sizes from the v2 manifest",
    );
    assert.equal(
      document.querySelector(
        `main a[href="${slowDownloadsBase}/philadelphia-shooting-victims.csv"]`,
      ),
      null,
      "SSR must not fall back to the legacy mutable CSV path",
    );

    const structuredData = [
      ...document.querySelectorAll('script[type="application/ld+json"]'),
    ]
      .map((script) => JSON.parse(script.textContent ?? "{}"))
      .find((value) => Array.isArray(value["@graph"]));
    const dataset = structuredData?.["@graph"].find(
      (entry) => entry["@id"] === `${canonicalBase}/data#dataset`,
    );
    const geographicDataset = structuredData?.["@graph"].find(
      (entry) =>
        entry["@id"] === `${canonicalBase}/data#geographic-reference-data`,
    );
    assert.equal(dataset?.distribution?.contentUrl, expectedUrls[0]);
    assert.equal(dataset?.distribution?.contentSize, "3064024 bytes");
    assert.deepEqual(
      geographicDataset?.distribution?.map((item) => item.contentSize),
      geographicReferenceDownloads.map(
        ([, , , byteSize]) => `${byteSize} bytes`,
      ),
    );
  } finally {
    dom?.window.close();
    if (processInstance.exitCode === null) {
      processInstance.kill("SIGTERM");
      await once(processInstance, "exit");
    }
  }
});

test("the Data page keeps v1 public download links working during the v2 cutover", async () => {
  const legacyBase = `${downloadsOrigin}/legacy-manifest`;
  const { origin, processInstance } = await startIsolatedNuxt(legacyBase);
  let dom;
  try {
    const response = await fetch(`${origin}${basePath}data`);
    const html = await response.text();
    dom = new JSDOM(html, { url: `${origin}${basePath}data` });
    const links = [
      ...dom.window.document.querySelectorAll("main a.civic-file-download-link"),
    ];

    assert.equal(response.status, 200);
    assert.equal(links.length, 9);
    assert.equal(
      links[0]?.getAttribute("href"),
      `${legacyBase}/philadelphia-shooting-victims.csv`,
    );
    assert.deepEqual(
      links.slice(1).map((link) => link.getAttribute("href")),
      geographicReferenceDownloads.map(
        ([, , filename]) => `${legacyBase}/geography/${filename}`,
      ),
    );
    assert.ok(
      links.every((link) =>
        normalizedText(
          link.querySelector(".civic-file-download-link__metadata"),
        ).includes("B]"),
      ),
    );
  } finally {
    dom?.window.close();
    if (processInstance.exitCode === null) {
      processInstance.kill("SIGTERM");
      await once(processInstance, "exit");
    }
  }
});

test("the Data page keeps its guided download path when no safe public CSV is configured", async () => {
  const unavailableBases = [
    { label: "missing", value: "" },
    {
      label: "internal API",
      value: "https://philly-gun-violence-dashboard-api.fly.dev/shootings",
    },
  ];

  for (const item of unavailableBases) {
    await test(item.label, async () => {
      const { origin, processInstance } = await startIsolatedNuxt(item.value);
      let dom;
      try {
        const response = await fetch(`${origin}${basePath}data`);
        const html = await response.text();
        dom = new JSDOM(html, { url: `${origin}${basePath}data` });
        const { document } = dom.window;
        const downloadGuide = document.querySelector(
          '[aria-labelledby="explore-download"]',
        );

        assert.equal(response.status, 200);
        assert.equal(
          downloadGuide?.querySelector(
            'a[href$="philadelphia-shooting-victims.csv"]',
          ),
          null,
        );
        assert.equal(document.querySelector(".civic-data-download"), null);
        assert.equal(
          document.querySelector(
            '[aria-labelledby="geographic-reference-downloads"]',
          ),
          null,
        );
        assert.equal(document.querySelector('main a[href$=".geojson"]'), null);
        assert.equal(document.querySelector('main a[href=""]'), null);
        assert.ok(
          downloadGuide?.querySelector(`a[href="${basePath}"]`),
          "Expected the link to explore and filter records to remain available",
        );
        assert.match(
          normalizedText(downloadGuide),
          /How to download a smaller set/i,
        );
        assert.match(
          normalizedText(downloadGuide),
          /Download Data button in the Explore controls/i,
        );
        assert.doesNotMatch(normalizedText(downloadGuide), /below the map/i);
        assert.match(normalizedText(downloadGuide), /filters/i);
        assert.match(normalizedText(downloadGuide), /CSV.*GeoJSON/i);

        const structuredData = [
          ...document.querySelectorAll('script[type="application/ld+json"]'),
        ]
          .map((script) => JSON.parse(script.textContent ?? "{}"))
          .find((value) => Array.isArray(value["@graph"]));
        const dataset = structuredData?.["@graph"].find(
          (entry) => entry["@type"] === "Dataset",
        );
        assert.equal("distribution" in dataset, false);
        assert.doesNotMatch(JSON.stringify(structuredData), /"contentUrl"\s*:/i);
      } finally {
        dom?.window.close();
        if (processInstance.exitCode === null) {
          processInstance.kill("SIGTERM");
          await once(processInstance, "exit");
        }
      }
    });
  }
});

test("the Data page keeps usable format-only links when download metadata is unavailable", async () => {
  const unavailableManifestBase = `${downloadsOrigin}/missing-manifest`;
  const { origin, processInstance } = await startIsolatedNuxt(
    unavailableManifestBase,
  );
  let dom;
  try {
    const response = await fetch(`${origin}${basePath}data`);
    const html = await response.text();
    dom = new JSDOM(html, { url: `${origin}${basePath}data` });
    const { document } = dom.window;
    const links = [
      ...document.querySelectorAll("main a.civic-file-download-link"),
    ];

    assert.equal(response.status, 200);
    assert.equal(links.length, 9);
    assert.deepEqual(
      links.map((link) =>
        normalizedText(
          link.querySelector(".civic-file-download-link__metadata"),
        ),
      ),
      ["[CSV]", ...Array(8).fill("[GEOJSON]")],
    );
    for (const link of links) {
      assert.ok(link.getAttribute("href"));
      assert.ok(link.getAttribute("download"));
      assert.ok(link.getAttribute("type"));
      assert.doesNotMatch(
        normalizedText(link),
        /undefined|null|NaN|,\s*\]/i,
      );
      assert.equal(
        link.querySelector("svg.civic-icon")?.getAttribute("aria-hidden"),
        "true",
      );
    }

    const structuredData = [
      ...document.querySelectorAll('script[type="application/ld+json"]'),
    ]
      .map((script) => JSON.parse(script.textContent ?? "{}"))
      .find((value) => Array.isArray(value["@graph"]));
    const distributions = structuredData["@graph"].flatMap((entry) => {
      if (!entry.distribution) return [];
      return Array.isArray(entry.distribution)
        ? entry.distribution
        : [entry.distribution];
    });
    assert.equal(distributions.length, 9);
    assert.ok(distributions.every((item) => !("contentSize" in item)));

    const manifestResponse = await fetch(
      `${origin}${basePath}api/public-download-manifest`,
    );
    assert.equal(manifestResponse.status, 200);
    assert.deepEqual(await manifestResponse.json(), { available: false });
    assert.equal(manifestResponse.headers.get("cache-control"), "no-store");
  } finally {
    dom?.window.close();
    if (processInstance.exitCode === null) {
      processInstance.kill("SIGTERM");
      await once(processInstance, "exit");
    }
  }
});

test("the AI-readable guide is concise, sourced, and stack-agnostic", async () => {
  const response = await fetch(`${nuxtOrigin}${basePath}llms.txt`);
  const body = await response.text();

  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/plain/);
  assert.match(body, /^# Philadelphia Gun Violence Dashboard$/m);
  assert.match(body, /^## Primary sources$/m);
  assert.match(body, /^## Using and citing the information$/m);
  assert.match(body, /^## Interpretation$/m);
  assert.match(body, /One row represents one shooting victim/);
  assert.match(body, /https:\/\/www\.nickhand\.dev\/philly-gun-violence-map\/methodology/);
  assert.match(body, /Use the Explorer's Download Data control/i);
  assert.match(body, /identify the measure, period or year, original publisher/i);
  assert.match(body, /not an official City of Philadelphia website/i);
  assert.doesNotMatch(
    body,
    /Vuetify|Netlify|updated daily|Current Statistics for Citation|\bAPI\b|fly\.dev|\/stats\.json|\/openapi(?:\.json)?|\/shootings(?:[/?#]|$)|\/meta(?:[/?#]|\s|$)/i,
  );
  assert.doesNotMatch(body, /<html/i);
});

test("sitemap contains only canonical content routes", async () => {
  const response = await fetch(`${nuxtOrigin}${basePath}sitemap.xml`);
  const xml = await response.text();
  const document = new JSDOM(xml, { contentType: "text/xml" }).window.document;
  const urls = [...document.querySelectorAll("url")];
  const locations = urls.map((url) => url.querySelector("loc")?.textContent);
  const expected = [
    canonicalBase,
    `${canonicalBase}/about`,
    `${canonicalBase}/data`,
    `${canonicalBase}/methodology`,
    `${canonicalBase}/stats`,
  ];

  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /xml/);
  assert.deepEqual([...locations].sort(), expected.sort());
  assert.equal(new Set(locations).size, locations.length);
  assert.ok(!xml.includes("stats.json"));
  assert.ok(!xml.includes("fly.dev"));

  for (const entry of urls) {
    assert.equal(
      entry.querySelector("lastmod"),
      null,
      "Coverage dates must not be presented as page-modification dates",
    );
  }
});

test("unknown routes return a noindex 404 page", async () => {
  const response = await fetch(`${nuxtOrigin}${basePath}not-a-real-page`, {
    headers: { accept: "text/html" },
  });
  const html = await response.text();
  const document = new JSDOM(html).window.document;

  assert.equal(response.status, 404);
  assert.equal(document.querySelector("h1")?.textContent?.trim(), "Page not found");
  assert.match(
    document.querySelector('meta[name="robots"]')?.getAttribute("content") ?? "",
    /noindex/,
  );
  assert.equal(document.querySelectorAll('link[rel="canonical"]').length, 0);
});
