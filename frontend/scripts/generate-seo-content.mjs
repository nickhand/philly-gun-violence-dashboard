/**
 * Deterministic post-build SEO content generation.
 *
 * Current statistics and the data-aware sitemap are server-rendered by the
 * FastAPI service. This script only adds evergreen crawler copy to the SPA
 * shell and creates the About page snapshot, so frontend builds never depend
 * on the production API or trigger data-driven Netlify deploys.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const CANONICAL_BASE = "https://www.nickhand.dev/philly-gun-violence-map";
const distDir = fileURLToPath(new URL("../dist", import.meta.url));

function buildHiddenHomeSummary() {
  return `
      <div style="position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);border:0">
        <h2>Philadelphia Gun Violence Data and Statistics</h2>
        <p>This open-source dashboard maps Philadelphia shooting victims and provides interactive filters, charts, and downloadable data. Public shooting and homicide datasets are updated daily.</p>
        <p><a href="${CANONICAL_BASE}/stats">Current server-rendered statistics and FAQ</a> | <a href="${CANONICAL_BASE}/about">About the dashboard and its data sources</a></p>
      </div>`;
}

function buildHiddenAboutSummary() {
  return `
      <div style="position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);border:0">
        <h2>About the Philadelphia Gun Violence Dashboard</h2>
        <p>Nick Hand first built this dashboard while serving as Director of Finance, Policy, and Data at the Philadelphia City Controller's Office. He now maintains it as an independent project, rebuilt with modern web tools and updated daily.</p>
        <p>Data sources include shooting victim records from the Philadelphia Police Department through OpenDataPhilly and official homicide counts from the PPD Statistics Unit. The dashboard also reports whether an automated incident-number search of Pennsylvania's Unified Judicial System portal returned a result.</p>
        <p>The dashboard only includes criminal shooting victims, not officer-involved shootings. Homicide totals include all homicides, not just gun deaths. All data is preliminary and may differ from other official sources.</p>
        <p><a href="${CANONICAL_BASE}/stats">Current statistics and FAQ</a> | <a href="${CANONICAL_BASE}/">Interactive dashboard</a> | <a href="https://github.com/nickhand/philly-gun-violence-dashboard">Source code on GitHub</a></p>
      </div>`;
}

function buildAboutStatic(indexHtml) {
  const aboutUrl = `${CANONICAL_BASE}/about`;
  const aboutTitle = "About | Philadelphia Gun Violence Dashboard";
  const aboutDescription =
    "Learn about the Philadelphia Gun Violence Dashboard, an open-source project that maps shooting incidents with public data updated daily. First built at the City Controller's Office, now independently maintained.";

  let html = indexHtml;
  html = html.replace(/<title>[^<]*<\/title>/, `<title>${aboutTitle}</title>`);
  for (const name of ["title", "twitter:title"]) {
    html = html.replace(
      new RegExp(`(name="${name}"\\s+content=")[^"]*(")`),
      `$1${aboutTitle}$2`,
    );
  }
  html = html.replace(
    /(property="og:title"\s+content=")[^"]*(")/,
    `$1${aboutTitle}$2`,
  );
  for (const name of ["description", "twitter:description"]) {
    html = html.replace(
      new RegExp(`(name="${name}"\\s+content=")[^"]*(")`),
      `$1${aboutDescription}$2`,
    );
  }
  html = html.replace(
    /(property="og:description"\s+content=")[^"]*(")/,
    `$1${aboutDescription}$2`,
  );
  html = html.replace(
    /(<link\s+rel="canonical"\s+href=")[^"]*(")/,
    `$1${aboutUrl}$2`,
  );
  html = html.replace(
    /(property="og:url"\s+content=")[^"]*(")/,
    `$1${aboutUrl}$2`,
  );
  html = html.replace(
    /(name="twitter:url"\s+content=")[^"]*(")/,
    `$1${aboutUrl}$2`,
  );

  const marker = '<div id="app">';
  const start = html.indexOf(marker);
  const bodyEnd = html.indexOf("</body>");
  const end = html.lastIndexOf("</div>", bodyEnd);
  if (start !== -1 && end > start) {
    html =
      html.slice(0, start + marker.length) +
      buildHiddenAboutSummary() +
      html.slice(end);
  }
  return html;
}

function main() {
  const indexPath = path.join(distDir, "index.html");
  if (!existsSync(indexPath)) {
    console.error(`[seo] ${indexPath} not found; run vite build first`);
    process.exit(1);
  }

  let html = readFileSync(indexPath, "utf-8");
  html = html.replace("<!-- __SEO_SUMMARY__ -->", buildHiddenHomeSummary());
  writeFileSync(indexPath, html);
  console.log("[seo] index.html: injected evergreen crawler summary");

  const aboutDir = path.join(distDir, "about");
  mkdirSync(aboutDir, { recursive: true });
  writeFileSync(path.join(aboutDir, "index.html"), buildAboutStatic(html));
  console.log("[seo] about/index.html: generated About page snapshot");
}

main();
