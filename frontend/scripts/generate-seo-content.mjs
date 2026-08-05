/**
 * Post-build SEO content generation.
 *
 * Runs after `vite build` and bakes crawler-visible content into the static
 * output so search engines and AI crawlers (which do not execute JavaScript)
 * can read current statistics. Replaces the retired Netlify prerendering setup.
 *
 * Outputs (all written into dist/):
 * - index.html: `<!-- __SEO_SUMMARY__ -->` placeholder replaced with a
 *   visually-hidden statistics summary (removed from the DOM when the Vue app
 *   mounts, so human visitors never see it), and `__DATA_THROUGH__` in the
 *   Dataset JSON-LD replaced with the data-through date.
 * - stats/index.html: a standalone static statistics + FAQ page.
 * - sitemap.xml: generated with current lastmod dates.
 *
 * The script degrades gracefully: if the API is unreachable, placeholders are
 * stripped, the sitemap is still generated, and the build succeeds.
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const API_BASE =
  process.env.SEO_API_BASE_URL ??
  "https://philly-gun-violence-dashboard-api.fly.dev";
const CANONICAL_BASE = "https://www.nickhand.dev/philly-gun-violence-map";

const distDir = fileURLToPath(new URL("../dist", import.meta.url));
const FETCH_TIMEOUT_MS = 30_000;

/** Fetch JSON with a timeout. */
async function getJson(pathname) {
  const res = await fetch(`${API_BASE}${pathname}`, {
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`GET ${pathname} -> ${res.status}`);
  return res.json();
}

/** Fetch NDJSON rows for one year and count fatal/nonfatal victims. */
async function countFatalNonfatal(rowsUrl) {
  const res = await fetch(`${API_BASE}${rowsUrl}`, {
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`GET ${rowsUrl} -> ${res.status}`);
  const text = await res.text();
  let fatal = 0;
  let nonfatal = 0;
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    const row = JSON.parse(line);
    if (row.fatal) fatal += 1;
    else nonfatal += 1;
  }
  return { fatal, nonfatal };
}

const fmt = (n) => Number(n).toLocaleString("en-US");

/** Format YYYY-MM-DD as e.g. "August 5, 2026" without timezone surprises. */
function fmtDate(isoDate) {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    timeZone: "UTC",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/** Gather all statistics needed for the generated content. */
async function fetchStats() {
  const [meta, shootingsMeta] = await Promise.all([
    getJson("/meta"),
    getJson("/shootings/meta"),
  ]);

  const years = shootingsMeta.years.map(Number).sort((a, b) => a - b);
  const currentYear = years[years.length - 1];
  const prevYear = currentYear - 1;
  const minYear = years[0];

  const currentYearMeta = shootingsMeta.years_meta[String(currentYear)];
  const [currentSplit, ...homicideTotals] = await Promise.all([
    countFatalNonfatal(currentYearMeta.rows_url),
    ...years.map((y) => getJson(`/homicides/${y}`).catch(() => null)),
  ]);

  const homicidesByYear = new Map(
    homicideTotals.filter(Boolean).map((t) => [t.year, t]),
  );

  const shootingsByYear = years.map((y) => ({
    year: y,
    victims: shootingsMeta.years_meta[String(y)].rows,
    homicides:
      y === currentYear
        ? (homicidesByYear.get(y)?.ytd ?? null)
        : (homicidesByYear.get(y)?.annual ?? null),
  }));

  const homicidesYtd = homicidesByYear.get(currentYear)?.ytd ?? null;
  // For past years the API returns `ytd` matched to the same calendar date,
  // enabling an apples-to-apples year-over-year comparison.
  const homicidesPrevYtd = homicidesByYear.get(prevYear)?.ytd ?? null;
  const pctChange =
    homicidesYtd !== null && homicidesPrevYtd
      ? Math.round(((homicidesYtd - homicidesPrevYtd) / homicidesPrevYtd) * 100)
      : null;

  const completedYears = shootingsByYear.filter((r) => r.year !== currentYear);
  const peak = completedYears.reduce((best, r) =>
    r.victims > best.victims ? r : best,
  );

  return {
    dataThrough: meta.shootings.data_through,
    lastUpdated: meta.shootings.last_updated,
    currentYear,
    prevYear,
    minYear,
    totalVictimsAllYears: shootingsMeta.rows,
    currentTotal: currentYearMeta.rows,
    currentFatal: currentSplit.fatal,
    currentNonfatal: currentSplit.nonfatal,
    homicidesYtd,
    homicidesPrevYtd,
    pctChange,
    peak,
    shootingsByYear,
  };
}

/** Sentences reused by both the hidden summary and the stats page. */
function buildSentences(s) {
  const asOf = fmtDate(s.dataThrough);
  const homicideChange =
    s.pctChange === null
      ? "."
      : s.pctChange === 0
        ? `, unchanged from the same point in ${s.prevYear}.`
        : `, ${s.pctChange > 0 ? "up" : "down"} ${Math.abs(s.pctChange)}% from ${fmt(s.homicidesPrevYtd)} homicides at the same point in ${s.prevYear}.`;
  const homicideSentence =
    s.homicidesYtd === null
      ? ""
      : `As of ${asOf}, Philadelphia has recorded ${fmt(s.homicidesYtd)} homicides in ${s.currentYear}${homicideChange}`;
  const shootingSentence = `As of ${asOf}, there have been ${fmt(s.currentTotal)} shooting victims in Philadelphia in ${s.currentYear}: ${fmt(s.currentFatal)} fatal and ${fmt(s.currentNonfatal)} nonfatal.`;
  const totalSentence = `Since ${s.minYear}, Philadelphia has recorded ${fmt(s.totalVictimsAllYears)} shooting victims.`;
  const peakSentence = `The worst year on record in this dataset is ${s.peak.year}, with ${fmt(s.peak.victims)} shooting victims${s.peak.homicides ? ` and ${fmt(s.peak.homicides)} total homicides` : ""}.`;
  return { asOf, homicideSentence, shootingSentence, totalSentence, peakSentence };
}

function buildYearTableRows(s) {
  return s.shootingsByYear
    .map(
      (r) =>
        `<tr><td>${r.year}${r.year === s.currentYear ? " (year to date)" : ""}</td><td>${fmt(r.victims)}</td><td>${r.homicides === null ? "—" : fmt(r.homicides)}</td></tr>`,
    )
    .join("\n            ");
}

/**
 * Visually-hidden summary injected inside #app in index.html. Crawlers that
 * don't run JavaScript read this; the Vue app replaces it on mount so it is
 * never rendered for (or announced to) real visitors.
 */
function buildHiddenSummary(s) {
  const t = buildSentences(s);
  return `
      <div style="position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);border:0">
        <h2>Philadelphia Gun Violence Statistics (as of ${t.asOf})</h2>
        <p>${t.homicideSentence}</p>
        <p>${t.shootingSentence}</p>
        <p>${t.totalSentence} ${t.peakSentence}</p>
        <table>
          <caption>Philadelphia shooting victims and homicides by year</caption>
          <thead><tr><th>Year</th><th>Shooting victims</th><th>Homicides</th></tr></thead>
          <tbody>
            ${buildYearTableRows(s)}
          </tbody>
        </table>
        <p>Source: Philadelphia Police Department shooting victims data via OpenDataPhilly, updated daily. Homicide counts from the PPD Statistics Unit and include all homicides, not only firearm deaths. All data is preliminary.</p>
        <p><a href="${CANONICAL_BASE}/stats">Full statistics and FAQ</a> | <a href="${CANONICAL_BASE}/about">About this dashboard</a></p>
      </div>`;
}

/** FAQ entries shared between the visible stats page and FAQPage JSON-LD. */
function buildFaq(s) {
  const t = buildSentences(s);
  const trendAnswer =
    s.pctChange === null
      ? `${t.shootingSentence} ${t.peakSentence}`
      : `Year-to-date homicides in ${s.currentYear} are ${s.pctChange > 0 ? "up" : "down"} ${Math.abs(s.pctChange)}% compared to the same point in ${s.prevYear}. ${t.peakSentence}`;
  return [
    {
      q: `How many shootings have there been in Philadelphia in ${s.currentYear}?`,
      a: t.shootingSentence,
    },
    {
      q: `How many homicides has Philadelphia had in ${s.currentYear}?`,
      a: `${t.homicideSentence} The homicide count includes all homicides, not only firearm deaths.`,
    },
    {
      q: "Is gun violence in Philadelphia increasing or decreasing?",
      a: trendAnswer,
    },
    {
      q: "Where does this data come from?",
      a: "Shooting victim data comes from the Philadelphia Police Department via OpenDataPhilly and is updated daily. Homicide totals come from the PPD Statistics Unit. Court records are linked from Pennsylvania's Unified Judicial System portal. All data is preliminary and may differ from other official sources.",
    },
    {
      q: "How can I download Philadelphia shooting data?",
      a: `You can download the data as CSV or GeoJSON from the interactive dashboard at ${CANONICAL_BASE}/, fetch machine-readable JSON from the public API at ${API_BASE}/shootings/meta, or get the source data from OpenDataPhilly.`,
    },
  ];
}

/** Standalone static statistics + FAQ page (no JavaScript required). */
function buildStatsPage(s) {
  const t = buildSentences(s);
  const faq = buildFaq(s);

  const faqJsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faq.map((f) => ({
      "@type": "Question",
      name: f.q,
      acceptedAnswer: { "@type": "Answer", text: f.a },
    })),
  };

  const faqHtml = faq
    .map(
      (f) => `
      <details class="faq-item" open>
        <summary><h3>${f.q}</h3></summary>
        <p>${f.a}</p>
      </details>`,
    )
    .join("\n");

  const title = `Philadelphia Gun Violence Statistics ${s.currentYear} | Shootings & Homicides`;
  const description = `${t.shootingSentence} ${t.homicideSentence} Updated daily from Philadelphia Police Department data.`;

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="robots" content="index, follow, max-snippet:-1" />
    <title>${title}</title>
    <meta name="description" content="${description}" />
    <meta name="author" content="Nick Hand" />
    <link rel="canonical" href="${CANONICAL_BASE}/stats" />
    <meta property="og:type" content="website" />
    <meta property="og:url" content="${CANONICAL_BASE}/stats" />
    <meta property="og:title" content="${title}" />
    <meta property="og:description" content="${description}" />
    <meta property="og:image" content="${CANONICAL_BASE}/og-image.png" />
    <meta name="twitter:card" content="summary_large_image" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      rel="stylesheet"
      href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap"
    />
    <script type="application/ld+json">
${JSON.stringify(faqJsonLd, null, 2)}
    </script>
    <style>
      * { box-sizing: border-box; }
      body {
        margin: 0;
        background: #2a3136;
        color: rgba(255, 255, 255, 0.85);
        font-family: Montserrat, system-ui, sans-serif;
        line-height: 1.7;
      }
      main { max-width: 900px; margin: 0 auto; padding: 48px 24px 64px; }
      h1 { color: #fff; font-size: 2rem; letter-spacing: -0.02em; margin: 0 0 8px; }
      h2 { color: #fff; font-size: 1.4rem; margin: 48px 0 16px; }
      .as-of { color: rgba(255, 255, 255, 0.6); margin: 0 0 32px; }
      .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }
      .card {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 20px 24px;
      }
      .card .num { font-size: 2rem; font-weight: 700; color: #7ab5e5; }
      .card .label { font-size: 0.9rem; color: rgba(255, 255, 255, 0.6); }
      table { width: 100%; border-collapse: collapse; margin-top: 8px; }
      th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); }
      th { color: rgba(255, 255, 255, 0.6); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.03em; }
      a { color: #7ab5e5; }
      .faq-item {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 4px 20px;
        margin-bottom: 12px;
      }
      .faq-item summary { cursor: pointer; }
      .faq-item h3 { display: inline; font-size: 1.05rem; color: #fff; }
      .note { font-size: 0.9rem; color: rgba(255, 255, 255, 0.6); }
      nav { padding: 20px 24px; max-width: 900px; margin: 0 auto; }
      nav a { margin-right: 20px; text-decoration: none; }
      footer { text-align: center; padding: 24px; color: rgba(255, 255, 255, 0.5); font-size: 0.85rem; }
    </style>
  </head>
  <body>
    <nav>
      <a href="/philly-gun-violence-map/">← Interactive Dashboard</a>
      <a href="/philly-gun-violence-map/about">About &amp; Methodology</a>
    </nav>
    <main>
      <h1>Philadelphia Gun Violence Statistics</h1>
      <p class="as-of">Data through ${t.asOf} · Updated daily from Philadelphia Police Department data</p>

      <div class="cards">
        <div class="card">
          <div class="num">${fmt(s.currentTotal)}</div>
          <div class="label">Shooting victims in ${s.currentYear} (${fmt(s.currentFatal)} fatal, ${fmt(s.currentNonfatal)} nonfatal)</div>
        </div>
        <div class="card">
          <div class="num">${s.homicidesYtd === null ? "—" : fmt(s.homicidesYtd)}</div>
          <div class="label">Homicides in ${s.currentYear} year to date${s.pctChange === null ? "" : ` (${s.pctChange > 0 ? "+" : ""}${s.pctChange}% vs. ${s.prevYear})`}</div>
        </div>
        <div class="card">
          <div class="num">${fmt(s.totalVictimsAllYears)}</div>
          <div class="label">Total shooting victims since ${s.minYear}</div>
        </div>
      </div>

      <h2>Summary</h2>
      <p>${t.homicideSentence}</p>
      <p>${t.shootingSentence} ${t.totalSentence} ${t.peakSentence}</p>

      <h2>Shooting victims and homicides by year</h2>
      <table>
        <thead><tr><th>Year</th><th>Shooting victims</th><th>Homicides</th></tr></thead>
        <tbody>
            ${buildYearTableRows(s)}
        </tbody>
      </table>
      <p class="note">Homicide totals include all homicides, not only firearm deaths, so they are not a subset of shooting victims. All data is preliminary and may differ from other official sources.</p>

      <h2>Frequently asked questions</h2>
      ${faqHtml}

      <h2>Get the data</h2>
      <p>
        Download CSV or GeoJSON from the <a href="/philly-gun-violence-map/">interactive dashboard</a>,
        fetch JSON from the <a href="${API_BASE}/shootings/meta">public API</a>,
        or get the source data from
        <a href="https://opendataphilly.org/datasets/shooting-victims/" rel="noopener">OpenDataPhilly</a>.
        The full pipeline and dashboard are open source
        <a href="https://github.com/nickhand/philly-gun-violence-dashboard" rel="noopener">on GitHub</a>.
      </p>
      <p class="note">
        This dashboard was originally built for the Philadelphia City Controller's Office and is now
        independently maintained and updated daily. See the
        <a href="/philly-gun-violence-map/about">about page</a> for methodology and limitations.
      </p>
    </main>
    <footer>Built in Wissahickon by <a href="https://www.nickhand.dev">Nick Hand</a></footer>
  </body>
</html>
`;
}

function buildSitemap(lastmod) {
  const urls = [
    { loc: `${CANONICAL_BASE}/`, changefreq: "daily", priority: "1.0" },
    { loc: `${CANONICAL_BASE}/stats`, changefreq: "daily", priority: "0.9" },
    { loc: `${CANONICAL_BASE}/about`, changefreq: "monthly", priority: "0.8" },
  ];
  const entries = urls
    .map(
      (u) => `  <url>
    <loc>${u.loc}</loc>
    <lastmod>${lastmod}</lastmod>
    <changefreq>${u.changefreq}</changefreq>
    <priority>${u.priority}</priority>
  </url>`,
    )
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${entries}
</urlset>
`;
}

async function main() {
  const indexPath = path.join(distDir, "index.html");
  if (!existsSync(indexPath)) {
    console.error(`[seo] ${indexPath} not found — run vite build first`);
    process.exit(1);
  }

  const buildDate = new Date().toISOString().slice(0, 10);
  let stats = null;
  try {
    stats = await fetchStats();
  } catch (err) {
    console.warn(`[seo] WARNING: failed to fetch stats from ${API_BASE}: ${err}`);
    console.warn("[seo] Falling back to placeholder cleanup only.");
  }

  let html = readFileSync(indexPath, "utf-8");
  html = html.replace("<!-- __SEO_SUMMARY__ -->", stats ? buildHiddenSummary(stats) : "");
  html = html.replace("__DATA_THROUGH__", stats ? stats.dataThrough : buildDate);
  writeFileSync(indexPath, html);
  console.log("[seo] index.html: injected hidden summary and dateModified");

  if (stats) {
    const statsDir = path.join(distDir, "stats");
    mkdirSync(statsDir, { recursive: true });
    writeFileSync(path.join(statsDir, "index.html"), buildStatsPage(stats));
    console.log("[seo] stats/index.html: generated static statistics page");
  }

  writeFileSync(
    path.join(distDir, "sitemap.xml"),
    buildSitemap(stats ? stats.dataThrough : buildDate),
  );
  console.log("[seo] sitemap.xml: generated");
}

await main();
