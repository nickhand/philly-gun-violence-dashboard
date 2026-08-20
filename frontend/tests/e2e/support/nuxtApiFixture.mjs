import { createServer } from "node:http";

import {
  rowsNdjson,
  shootingRows,
} from "../../fixtures/shootings.ts";

const host = "127.0.0.1";
const port = Number(process.env.NUXT_E2E_API_PORT ?? 4181);
const allowedOrigin =
  process.env.NUXT_E2E_ALLOWED_ORIGIN ?? "http://127.0.0.1:4180";

const previousYearRows = shootingRows.slice(0, 2).map((row, index) => ({
  ...row,
  date: `2025-0${index + 1}-${index === 0 ? "05" : "10"}`,
  dateInMs: Date.UTC(2025, index, index === 0 ? 5 : 10),
  dc_key: `2025-0${index + 1}`,
  unique_id: 101 + index,
  year: 2025,
}));

const previousYearNdjson = previousYearRows
  .map((row) => JSON.stringify(row))
  .join("\n");

function categorySummary(rows, year) {
  const count = (field, value) =>
    rows.filter((row) => row[field] === value).length;
  const fatal = rows.filter((row) => row.fatal).length;

  return {
    year,
    total: rows.length,
    outcome: { true: fatal, false: rows.length - fatal },
    court: {
      true: count("has_court_case", true),
      false: count("has_court_case", false),
      null: count("has_court_case", null),
    },
    gender: { M: count("sex", "M"), F: count("sex", "F") },
    race: {
      W: count("race", "W"),
      B: count("race", "B"),
      H: count("race", "H"),
      A: count("race", "A"),
      "Other/Unknown": count("race", "Other/Unknown"),
    },
    age: {
      "Younger than 18": count("age_group", "Younger than 18"),
      "18 to 30": count("age_group", "18 to 30"),
      "31 to 45": count("age_group", "31 to 45"),
      "Older than 45": count("age_group", "Older than 45"),
      Unknown: count("age_group", "Unknown"),
    },
  };
}

const shootingsManifest = {
  version: "nuxt-e2e-v1",
  generated_at: "2026-07-29T12:00:00Z",
  rows: shootingRows.length + previousYearRows.length,
  years: [2026, 2025],
  years_meta: {
    2026: {
      rows: shootingRows.length,
      rows_url: "/shootings/rows/nuxt-e2e-v1/2026.ndjson",
    },
    2025: {
      rows: previousYearRows.length,
      rows_url: "/shootings/rows/nuxt-e2e-v1/2025.ndjson",
    },
  },
};

const stats = {
  shootings_data_through: "2026-07-28",
  homicides_data_through: "2026-07-29",
  current_year: 2026,
  previous_year: 2025,
  minimum_year: 2025,
  total_victims_all_years: shootingRows.length + previousYearRows.length,
  current_total: shootingRows.length,
  current_fatal: shootingRows.filter((row) => row.fatal).length,
  current_nonfatal: shootingRows.filter((row) => !row.fatal).length,
  shootings_previous_ytd: 2,
  shooting_percent_change: 100,
  homicides_ytd: 10,
  homicides_previous_ytd: 8,
  homicide_percent_change: 25,
  peak: { year: 2026, victims: shootingRows.length, homicides: 10 },
  years: [
    { year: 2026, victims: shootingRows.length, homicides: 10 },
    { year: 2025, victims: previousYearRows.length, homicides: 8 },
  ],
  category_summaries: [
    categorySummary(previousYearRows, 2025),
    categorySummary(shootingRows, 2026),
    categorySummary([...previousYearRows, ...shootingRows], null),
  ],
};

const emptyFeatureCollection = {
  type: "FeatureCollection",
  features: [],
};

function responseHeaders(contentType) {
  return {
    "access-control-allow-headers": "Accept, Content-Type",
    "access-control-allow-methods": "GET, OPTIONS",
    "access-control-allow-origin": allowedOrigin,
    "cache-control": "no-store",
    "content-type": contentType,
    vary: "Origin",
  };
}

function send(response, status, contentType, body = "") {
  response.writeHead(status, responseHeaders(contentType));
  response.end(body);
}

function sendJson(response, body) {
  send(response, 200, "application/json; charset=utf-8", JSON.stringify(body));
}

const server = createServer((request, response) => {
  if (request.method === "OPTIONS") {
    return send(response, 204, "text/plain; charset=utf-8");
  }

  const url = new URL(request.url ?? "/", `http://${host}:${port}`);
  if (url.pathname === "/health") {
    return send(response, 200, "text/plain; charset=utf-8", "ok");
  }
  if (url.pathname === "/stats.json") return sendJson(response, stats);
  if (url.pathname === "/shootings/meta") {
    return sendJson(response, shootingsManifest);
  }
  if (url.pathname === "/shootings/rows/nuxt-e2e-v1/2026.ndjson") {
    return send(
      response,
      200,
      "application/x-ndjson; charset=utf-8",
      rowsNdjson,
    );
  }
  if (url.pathname === "/shootings/rows/nuxt-e2e-v1/2025.ndjson") {
    return send(
      response,
      200,
      "application/x-ndjson; charset=utf-8",
      previousYearNdjson,
    );
  }
  if (url.pathname === "/meta") {
    const dataset = {
      data_through: "2026-07-28",
      last_updated: "2026-07-29T12:00:00Z",
    };
    return sendJson(response, {
      shootings: { ...dataset, row_count: shootingsManifest.rows },
      homicides: dataset,
      courts: dataset,
    });
  }
  if (url.pathname.startsWith("/boundaries/")) {
    return sendJson(response, emptyFeatureCollection);
  }
  if (url.pathname === "/streets") {
    return sendJson(response, {
      ...emptyFeatureCollection,
      limit: 2_000,
      offset: 0,
      next_offset: null,
      total: 0,
    });
  }
  if (url.pathname.startsWith("/tiles/")) {
    return send(response, 200, "application/vnd.mapbox-vector-tile", Buffer.alloc(0));
  }

  return send(response, 404, "text/plain; charset=utf-8", "Not found");
});

server.listen(port, host, () => {
  console.log(`Nuxt browser API fixture listening at http://${host}:${port}`);
});

function shutdown() {
  server.close(() => process.exit(0));
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
