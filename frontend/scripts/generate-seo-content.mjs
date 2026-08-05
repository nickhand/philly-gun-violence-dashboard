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
      // HTML variant for the visible page only; JSON-LD keeps the plain text.
      aHtml: `Download CSV or GeoJSON from the <a href="/philly-gun-violence-map/">interactive dashboard</a>, fetch JSON from the <a href="${API_BASE}/shootings/meta">public API</a>, or get the source data from <a href="https://opendataphilly.org/datasets/shooting-victims/" rel="noopener">OpenDataPhilly</a>.`,
    },
  ];
}

/**
 * Colored-span summary paragraphs for the stats page only. The plain-text
 * sentences from buildSentences() remain the source for the meta description
 * and JSON-LD; these variants add the dashboard's semantic colors (fatal red,
 * nonfatal yellow, dates/years muted green).
 */
function buildColoredSummary(s) {
  const asOf = fmtDate(s.dataThrough);
  const homicideChange =
    s.pctChange === null
      ? "."
      : s.pctChange === 0
        ? `, unchanged from the same point in <span class="c-date">${s.prevYear}</span>.`
        : `, ${s.pctChange > 0 ? "up" : "down"} ${Math.abs(s.pctChange)}% from ${fmt(s.homicidesPrevYtd)} homicides at the same point in <span class="c-date">${s.prevYear}</span>.`;
  const p1 =
    s.homicidesYtd === null
      ? ""
      : `As of ${asOf}, Philadelphia has recorded <span class="c-fatal">${fmt(s.homicidesYtd)} homicides</span> in ${s.currentYear}${homicideChange}`;
  const p2 =
    `There have been ${fmt(s.currentTotal)} shooting victims this year: ` +
    `<span class="c-fatal">${fmt(s.currentFatal)} fatal</span> and <span class="c-nonfatal">${fmt(s.currentNonfatal)} nonfatal</span>. ` +
    `Since <span class="c-date">${s.minYear}</span>, Philadelphia has recorded ${fmt(s.totalVictimsAllYears)} shooting victims. ` +
    `The worst year on record is <span class="c-date">${s.peak.year}</span>, with ${fmt(s.peak.victims)} victims${s.peak.homicides ? ` and ${fmt(s.peak.homicides)} total homicides` : ""}.`;
  return [p1, p2].filter(Boolean);
}

/** Standalone static statistics + FAQ page (no JavaScript required). */
function buildStatsPage(s) {
  const t = buildSentences(s);
  const faq = buildFaq(s);
  const summaryParagraphs = buildColoredSummary(s);
  const maxVictims = Math.max(...s.shootingsByYear.map((r) => r.victims));

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
      <div class="faq-row">
        <h3>${f.q}</h3>
        <p>${f.aHtml ?? f.a}</p>
      </div>`,
    )
    .join("\n");

  const tableRows = s.shootingsByYear
    .map((r) => {
      const yearCell =
        r.year === s.currentYear
          ? `<td class="yr yr-current">${r.year} <span class="ytd">YTD</span></td>`
          : `<td class="yr">${r.year}</td>`;
      const pct = Math.round((r.victims / maxVictims) * 100);
      return `<tr>${yearCell}<td class="num">${fmt(r.victims)}</td><td class="bar-cell"><div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div></td><td class="num">${r.homicides === null ? "—" : fmt(r.homicides)}</td></tr>`;
    })
    .join("\n            ");

  const trendDetail =
    s.pctChange === null
      ? ""
      : s.pctChange === 0
        ? `unchanged vs. ${s.prevYear}`
        : `${s.pctChange > 0 ? "up" : "down"} ${Math.abs(s.pctChange)}% vs. ${s.prevYear}`;

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
      href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600&display=swap"
    />
    <script type="application/ld+json">
${JSON.stringify(faqJsonLd, null, 2)}
    </script>
    <style>
      * { box-sizing: border-box; }
      body {
        margin: 0;
        background: #353d42;
        color: rgba(255, 255, 255, 0.8);
        font-family: Avenir, Helvetica, Arial, sans-serif;
        line-height: 1.7;
      }
      h1, h2, h3 { font-family: Montserrat, sans-serif; }
      a { color: #7ab5e5; text-decoration: none; transition: color 0.2s; }
      a:hover { color: #9ecbf0; text-decoration: underline; }
      a:focus-visible { outline: 3px solid #7ab5e5; outline-offset: 2px; }
      nav { display: flex; justify-content: flex-end; gap: 10px; padding: 16px 24px; }
      nav a {
        display: inline-flex;
        align-items: center;
        height: 38px;
        border: 1px solid rgba(255, 255, 255, 0.72);
        border-radius: 4px;
        padding: 0 14px;
        font-size: 15px;
        color: #ffffff;
        transition: border-color 0.2s;
      }
      nav a:hover { border-color: #ffffff; color: #ffffff; text-decoration: none; }
      main { max-width: 860px; margin: 0 auto; padding: 0 44px 64px; }
      .hero { text-align: center; padding: 28px 0 36px; }
      .kicker {
        font-family: Montserrat, sans-serif;
        font-weight: 600;
        font-size: 11px;
        letter-spacing: 0.24em;
        text-transform: uppercase;
        color: #b2beb5;
        margin: 0 0 14px;
      }
      h1 { font-size: 40px; font-weight: 500; line-height: 1.15; color: #ffffff; margin: 0 0 12px; }
      .hero-sub { font-size: 14px; color: rgba(255, 255, 255, 0.6); margin: 0; }
      .figures {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        border-top: 1px solid rgba(255, 255, 255, 0.12);
        border-bottom: 1px solid rgba(255, 255, 255, 0.12);
        padding: 26px 0;
      }
      .figure-cell { text-align: center; border-left: 1px solid rgba(255, 255, 255, 0.1); }
      .figure-cell:first-child { border-left: none; }
      .figure {
        font-family: Montserrat, sans-serif;
        font-weight: 500;
        font-size: 44px;
        color: #ffffff;
        font-variant-numeric: tabular-nums;
        line-height: 1;
      }
      .figure-label {
        font-size: 12px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: rgba(255, 255, 255, 0.55);
        margin-top: 10px;
      }
      .figure-detail { font-size: 13px; margin-top: 6px; }
      .c-fatal { color: #ff8a8a; }
      .c-nonfatal { color: #e5dc8e; }
      .c-date { color: #b2beb5; }
      .section-label {
        font-family: Montserrat, sans-serif;
        font-weight: 600;
        font-size: 11px;
        letter-spacing: 0.2em;
        text-transform: uppercase;
        color: #b2beb5;
        margin: 56px 0 14px;
      }
      .summary p { font-size: 15px; line-height: 1.75; max-width: 700px; margin: 0 0 14px; }
      .summary p:last-child { margin-bottom: 0; }
      table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
      th {
        font-family: Montserrat, sans-serif;
        font-weight: 600;
        font-size: 10.5px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: rgba(255, 255, 255, 0.5);
        text-align: left;
        padding: 8px 12px 8px 0;
        border-bottom: 2px solid rgba(255, 255, 255, 0.3);
      }
      th.num, td.num { text-align: right; }
      td { font-size: 13.5px; padding: 8px 12px 8px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.08); }
      td.yr { color: #b2beb5; }
      td.yr-current { color: #ffffff; }
      .ytd { font-size: 10.5px; letter-spacing: 0.08em; color: rgba(255, 255, 255, 0.45); }
      .bar-cell { width: 48%; padding-right: 24px; padding-left: 16px; }
      .bar-track { height: 7px; background: rgba(255, 255, 255, 0.06); }
      .bar-fill { height: 7px; background: #6a90a5; }
      .note { font-size: 12.5px; line-height: 1.6; color: rgba(255, 255, 255, 0.55); margin-top: 16px; }
      .faq-row {
        display: grid;
        grid-template-columns: 340px 1fr;
        gap: 20px;
        padding: 18px 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.09);
      }
      .faq-row:last-child { border-bottom: none; }
      .faq-row h3 { font-size: 14px; font-weight: 600; color: #ffffff; line-height: 1.5; margin: 0; }
      .faq-row p { font-size: 13.5px; line-height: 1.65; color: rgba(255, 255, 255, 0.7); margin: 0; }
      .get-data { border-top: 1px solid rgba(255, 255, 255, 0.12); margin-top: 56px; }
      .get-data .section-label { margin-top: 26px; }
      .get-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; }
      .get-cell { border-top: 2px solid rgba(255, 255, 255, 0.3); padding-top: 12px; }
      .get-cell h3 { font-size: 13.5px; font-weight: 600; color: #ffffff; margin: 0 0 6px; }
      .get-cell p { font-size: 12.5px; line-height: 1.6; color: rgba(255, 255, 255, 0.6); margin: 0; }
      .footnote { font-size: 12.5px; line-height: 1.6; color: rgba(255, 255, 255, 0.55); margin-top: 24px; }
      footer { text-align: center; padding: 24px; font-size: 13px; color: rgba(255, 255, 255, 0.7); }
      footer a { color: #b2beb5; text-decoration: underline; text-underline-offset: 0.2em; }
      footer a:hover { color: #ffffff; }
      .sr-only {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
      }
      @media (prefers-reduced-motion: reduce) {
        * { transition-duration: 0.01ms !important; }
      }
      @media (max-width: 700px) {
        h1 { font-size: 28px; }
        main { padding: 0 24px 48px; }
        .figures { grid-template-columns: 1fr; gap: 20px; }
        .figure-cell { border-left: none; border-top: 1px solid rgba(255, 255, 255, 0.09); padding-top: 20px; }
        .figure-cell:first-child { border-top: none; padding-top: 0; }
        .faq-row { grid-template-columns: 1fr; gap: 6px; }
        .get-grid { grid-template-columns: 1fr; }
      }
      @media (max-width: 480px) {
        .bar-cell { display: none; }
      }
    </style>
  </head>
  <body>
    <nav>
      <a href="/philly-gun-violence-map/">← Dashboard</a>
      <a href="/philly-gun-violence-map/about">About</a>
    </nav>
    <main>
      <header class="hero">
        <p class="kicker">Statistics · Data through ${t.asOf}</p>
        <h1>Philadelphia Gun Violence Statistics</h1>
        <p class="hero-sub">Updated daily from Philadelphia Police Department data · No JavaScript required</p>
      </header>

      <div class="figures">
        <div class="figure-cell">
          <div class="figure">${fmt(s.currentTotal)}</div>
          <div class="figure-label">Shooting victims in ${s.currentYear}</div>
          <div class="figure-detail"><span class="c-fatal">${fmt(s.currentFatal)} fatal</span> · <span class="c-nonfatal">${fmt(s.currentNonfatal)} nonfatal</span></div>
        </div>
        <div class="figure-cell">
          <div class="figure">${s.homicidesYtd === null ? "—" : fmt(s.homicidesYtd)}</div>
          <div class="figure-label">Homicides year to date</div>
          ${trendDetail ? `<div class="figure-detail"><span class="c-date">${trendDetail}</span></div>` : ""}
        </div>
        <div class="figure-cell">
          <div class="figure">${fmt(s.totalVictimsAllYears)}</div>
          <div class="figure-label">Total victims since ${s.minYear}</div>
          <div class="figure-detail"><span class="c-date">peak year ${s.peak.year} · ${fmt(s.peak.victims)}</span></div>
        </div>
      </div>

      <section class="summary">
        <h2 class="section-label">Summary</h2>
        ${summaryParagraphs.map((p) => `<p>${p}</p>`).join("\n        ")}
      </section>

      <section>
        <h2 class="section-label">Shooting victims and homicides by year</h2>
        <table>
          <thead><tr><th>Year</th><th class="num">Victims</th><th class="bar-cell"><span class="sr-only">Victims as share of peak year</span></th><th class="num">Homicides</th></tr></thead>
          <tbody>
            ${tableRows}
          </tbody>
        </table>
        <p class="note">Homicide totals include all homicides, not only firearm deaths, so they are not a subset of shooting victims. All data is preliminary and may differ from other official sources.</p>
      </section>

      <section>
        <h2 class="section-label">Frequently asked questions</h2>
      ${faqHtml}
      </section>

      <section class="get-data">
        <h2 class="section-label">Get the data</h2>
        <div class="get-grid">
          <div class="get-cell">
            <h3>CSV / GeoJSON</h3>
            <p>Filtered downloads from the <a href="/philly-gun-violence-map/">interactive dashboard</a>.</p>
          </div>
          <div class="get-cell">
            <h3>Public API</h3>
            <p>Machine-readable JSON at <a href="${API_BASE}/shootings/meta">/shootings/meta</a>.</p>
          </div>
          <div class="get-cell">
            <h3>Source &amp; code</h3>
            <p><a href="https://opendataphilly.org/datasets/shooting-victims/" rel="noopener">OpenDataPhilly</a> · open source <a href="https://github.com/nickhand/philly-gun-violence-dashboard" rel="noopener">on GitHub</a>.</p>
          </div>
        </div>
        <p class="footnote">This dashboard was originally built for the Philadelphia City Controller's Office and is now independently maintained and updated daily. See the <a href="/philly-gun-violence-map/about">about page</a> for methodology and limitations.</p>
      </section>
    </main>
    <footer>Built in Wissahickon by <a href="https://www.nickhand.dev">Nick Hand</a> • ${s.currentYear}</footer>
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
