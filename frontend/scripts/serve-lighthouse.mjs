import { createReadStream, statSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const host = "127.0.0.1";
const port = 4174;
const basePath = "/philly-gun-violence-map/";
const distRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "dist");

const shootingRows = [
  {
    dc_key: "2026-lighthouse-1",
    race: "B",
    sex: "M",
    fatal: false,
    date: "2026-01-05",
    age_group: "18 to 30",
    has_court_case: true,
    age: 24,
    street_name: "MARKET ST",
    block_number: 1200,
    zip_code: "19107",
    council_district: "1",
    police_district: "6",
    neighborhood: "Center City",
    school_name: "Test School",
    house_district: "182",
    senate_district: "1",
    segment_id: "segment-1",
    weekday: 1,
    timeInMs: 3_600_000,
    dateInMs: 1_767_571_200_000,
    unique_id: 1,
    lon: -75.1602,
    lat: 39.9526,
    year: 2026,
  },
];

const datasetMeta = {
  last_updated: "2026-07-29T12:00:00Z",
  data_through: "2026-07-28",
};

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

function send(response, status, contentType, body) {
  response.writeHead(status, {
    "cache-control": "no-store",
    "content-type": contentType,
  });
  response.end(body);
}

function sendJson(response, body) {
  send(response, 200, "application/json; charset=utf-8", JSON.stringify(body));
}

function serveFile(response, filePath) {
  response.writeHead(200, {
    "cache-control": "no-store",
    "content-type":
      contentTypes[extname(filePath)] ?? "application/octet-stream",
  });
  createReadStream(filePath).pipe(response);
}

const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", `http://${host}:${port}`);

  if (url.pathname === "/shootings/meta") {
    return sendJson(response, {
      version: "lighthouse-fixture-v1",
      generated_at: "2026-07-29T12:00:00Z",
      rows: shootingRows.length,
      years: [2026],
      years_meta: {
        2026: {
          rows: shootingRows.length,
          rows_url: "/shootings/rows/lighthouse-fixture-v1/2026.ndjson",
        },
      },
    });
  }

  if (url.pathname === "/shootings/rows/lighthouse-fixture-v1/2026.ndjson") {
    return send(
      response,
      200,
      "application/x-ndjson; charset=utf-8",
      shootingRows.map((row) => JSON.stringify(row)).join("\n"),
    );
  }

  if (url.pathname === "/homicides/2026") {
    return sendJson(response, { year: 2026, annual: null, ytd: 10 });
  }

  if (url.pathname === "/meta") {
    return sendJson(response, {
      shootings: datasetMeta,
      homicides: datasetMeta,
      courts: datasetMeta,
    });
  }

  if (url.pathname.startsWith("/boundaries/")) {
    return sendJson(response, {
      type: "FeatureCollection",
      features: [],
    });
  }

  if (url.pathname === "/streets") {
    return sendJson(response, {
      type: "FeatureCollection",
      features: [],
      limit: 2_000,
      offset: 0,
      next_offset: null,
      total: 0,
    });
  }

  if (!url.pathname.startsWith(basePath)) {
    return send(response, 404, "text/plain; charset=utf-8", "Not found");
  }

  const relativePath = decodeURIComponent(url.pathname.slice(basePath.length));
  const requestedPath = resolve(distRoot, relativePath || "index.html");
  const safePrefix = `${distRoot}${sep}`;

  if (
    requestedPath !== resolve(distRoot, "index.html") &&
    !requestedPath.startsWith(safePrefix)
  ) {
    return send(response, 403, "text/plain; charset=utf-8", "Forbidden");
  }

  try {
    if (statSync(requestedPath).isFile()) {
      return serveFile(response, requestedPath);
    }
  } catch {
    // Vue Router history fallback is handled below.
  }

  return serveFile(response, resolve(distRoot, "index.html"));
});

server.listen(port, host, () => {
  console.log(
    `Lighthouse fixture server listening at http://${host}:${port}${basePath}`,
  );
});

function shutdown() {
  server.close(() => process.exit(0));
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
