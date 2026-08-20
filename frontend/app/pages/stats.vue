<script setup lang="ts">
import {
  formatDataDate as formatDate,
  formatDataNumber as formatNumber,
} from "~/utils/formatData";
import {
  createDashboardDatasetProvenance,
  createDashboardPageProvenance,
  createPublicSourceEntities,
  getDashboardEntityIds,
} from "~/utils/structuredData";

const { canonicalBaseUrl } = useRuntimeConfig().public;
const siteUrl = String(canonicalBaseUrl).replace(/\/$/, "");
const canonicalUrl = `${siteUrl}/stats`;
const entityIds = getDashboardEntityIds(siteUrl);

const {
  data: stats,
  error: statsError,
  refresh,
  status,
} = await useStatsSnapshot();

const annualRows = computed(() =>
  [...(stats.value?.years ?? [])].sort((left, right) => left.year - right.year),
);

const peakVictimCount = computed(() => {
  return Math.max(
    0,
    ...annualRows.value.map((year) => year.victims),
  );
});

function annualBarStyle(
  value: number,
  peak: number,
): Record<string, string> | undefined {
  if (peak <= 0) return undefined;

  const percentage = Math.min(100, Math.max(0, (value / peak) * 100));
  return { width: `${percentage.toFixed(1)}%` };
}

function formatSamePointComparison(
  currentCount: number | null | undefined,
  previousCount: number | null | undefined,
  percentChange: number | null | undefined,
  previousYear: number,
): string {
  const comparison = `the same point in ${previousYear}`;
  if (typeof currentCount !== "number") return `Comparison with ${comparison} is not available.`;
  if (typeof previousCount !== "number") return `Comparison with ${comparison} is not available.`;

  const previous = formatNumber(previousCount);
  const difference = currentCount - previousCount;
  if (difference === 0) {
    return `No change from ${comparison} (${previous}).`;
  }
  if (typeof percentChange !== "number") {
    return `The total at ${comparison} was ${previous}.`;
  }

  const direction = difference > 0 ? "higher" : "lower";
  const change = percentChange === 0 ? "less than 1%" : `${Math.abs(percentChange)}%`;
  return `${change} ${direction} than the ${previous} reported at ${comparison}.`;
}

const shootingComparison = computed(() => {
  const snapshot = stats.value;
  if (!snapshot) return null;
  return formatSamePointComparison(
    snapshot.current_total,
    snapshot.shootings_previous_ytd,
    snapshot.shooting_percent_change,
    snapshot.previous_year,
  );
});

const homicideComparison = computed(() => {
  const snapshot = stats.value;
  if (!snapshot) return null;
  return formatSamePointComparison(
    snapshot.homicides_ytd,
    snapshot.homicides_previous_ytd,
    snapshot.homicide_percent_change,
    snapshot.previous_year,
  );
});

function printCountsByYear() {
  if (import.meta.client) window.print();
}

const pageTitle = computed(() =>
  stats.value
    ? `Philadelphia gun violence statistics, ${stats.value.current_year} | Philadelphia Gun Violence Dashboard`
    : "Philadelphia gun violence statistics | Philadelphia Gun Violence Dashboard",
);

const description = computed(() => {
  const snapshot = stats.value;
  if (!snapshot) {
    return "Current and historical Philadelphia shooting-victim counts and Philadelphia Police Department homicide totals, with source dates and public data links.";
  }

  const shootingSummary = `In ${snapshot.current_year}, Philadelphia Police Department data report ${formatNumber(snapshot.current_total)} shooting victims through ${formatDate(snapshot.shootings_data_through)} (${formatNumber(snapshot.current_fatal)} fatal and ${formatNumber(snapshot.current_nonfatal)} nonfatal)`;
  const homicideSummary =
    snapshot.homicides_ytd === null
      ? "The citywide homicide total is temporarily unavailable"
      : `The Philadelphia Police Department reports ${formatNumber(snapshot.homicides_ytd)} total homicides through ${formatDate(snapshot.homicides_data_through)}`;
  return `${shootingSummary}. ${homicideSummary}.`;
});

const structuredData = computed(() => {
  const snapshot = stats.value;
  const graph: Record<string, unknown>[] = [
    {
      "@type": "WebPage",
      "@id": entityIds.statsPage,
      name: "Philadelphia shooting-victim and homicide statistics",
      url: canonicalUrl,
      description: description.value,
      ...createDashboardPageProvenance(entityIds),
      ...(snapshot
        ? {
            mainEntity: { "@id": entityIds.statsDataset },
            about: { "@id": entityIds.statsDataset },
          }
        : {}),
    },
  ];

  if (snapshot) {
    graph.push({
      "@type": "Dataset",
      "@id": entityIds.statsDataset,
      name: "Philadelphia shooting-victim and homicide statistics",
      description:
        "Annual and year-to-date shooting-victim records and citywide homicide totals from Philadelphia Police Department public data.",
      url: canonicalUrl,
      ...createDashboardDatasetProvenance(entityIds),
      spatialCoverage: "Philadelphia, Pennsylvania",
      temporalCoverage: `${snapshot.minimum_year}-01-01/${[
        snapshot.shootings_data_through,
        snapshot.homicides_data_through,
      ].sort().at(-1)}`,
      measurementTechnique: `${siteUrl}/methodology`,
      variableMeasured: [
        {
          "@type": "PropertyValue",
          name: "Shooting victims",
          description:
            "People reported as shooting victims in Philadelphia Police Department public records after the dashboard's documented exclusions.",
        },
        {
          "@type": "PropertyValue",
          name: "Fatal shooting victims",
        },
        {
          "@type": "PropertyValue",
          name: "Nonfatal shooting victims",
        },
        {
          "@type": "PropertyValue",
          name: "Homicides",
          description:
            "All citywide homicides reported by the Philadelphia Police Department, whether or not a gun was involved.",
        },
      ],
      isBasedOn: [
        { "@id": entityIds.shootingSourceDataset },
        { "@id": entityIds.homicideSourceDataset },
      ],
      citation: [
        `Philadelphia Gun Violence Dashboard. “Philadelphia shooting-victim and homicide statistics.” Shooting-victim records through ${formatDate(snapshot.shootings_data_through)}; Philadelphia Police Department homicide totals through ${formatDate(snapshot.homicides_data_through)}. ${canonicalUrl}.`,
        { "@id": entityIds.shootingSourceDataset },
        { "@id": entityIds.homicideSourceDataset },
      ],
      keywords: [
        "Philadelphia gun violence",
        "shooting victims",
        "homicides",
        "public safety data",
      ],
      isAccessibleForFree: true,
    });
    graph.push(...createPublicSourceEntities(entityIds));
  }

  return { "@context": "https://schema.org", "@graph": graph };
});

useSeoMeta({
  title: () => pageTitle.value,
  description: () => description.value,
  ogType: "website",
  ogTitle: () => pageTitle.value,
  ogDescription: () => description.value,
  ogUrl: canonicalUrl,
  ogImage: `${siteUrl}/og-image.png`,
  twitterCard: "summary_large_image",
  twitterTitle: () => pageTitle.value,
  twitterDescription: () => description.value,
  twitterImage: `${siteUrl}/og-image.png`,
});

useHead(() => ({
  link: [{ rel: "canonical", href: canonicalUrl }],
  script: [
    {
      type: "application/ld+json",
      innerHTML: JSON.stringify(structuredData.value).replace(/</g, "\\u003c"),
    },
  ],
}));
</script>

<template>
  <main id="main-content" class="civic-reference-page" tabindex="-1">
    <header class="grid-container civic-container civic-page-intro">
      <h1>Philadelphia shooting-victim and homicide statistics</h1>
      <p class="usa-intro">
        Current and annual counts from public Philadelphia Police Department
        (PPD) data. Current-year figures are year to date, and each source has
        its own reporting date.
      </p>
    </header>

    <div class="grid-container civic-container civic-content-section">
      <template v-if="stats">
        <section
          class="civic-stats-current civic-stats-current--compact"
          aria-labelledby="current-picture"
        >
          <h2 id="current-picture">Current year totals</h2>
          <div class="civic-stats-current__grid">
            <section
              class="civic-current-measure"
              aria-labelledby="current-shooting-victims"
            >
              <h3 id="current-shooting-victims" class="civic-stat-label">
                Shooting victims
              </h3>
              <p class="civic-current-through">
                Through
                <time :datetime="stats.shootings_data_through">
                  {{ formatDate(stats.shootings_data_through) }}
                </time>
              </p>
              <p class="civic-stat-total">
                {{ formatNumber(stats.current_total) }}
              </p>
              <dl class="civic-outcome-list">
                <div class="civic-outcome-list__fatal">
                  <dt>Fatal</dt>
                  <dd>{{ formatNumber(stats.current_fatal) }}</dd>
                </div>
                <div class="civic-outcome-list__nonfatal">
                  <dt>Nonfatal</dt>
                  <dd>{{ formatNumber(stats.current_nonfatal) }}</dd>
                </div>
              </dl>
              <p v-if="shootingComparison" class="civic-current-comparison">
                {{ shootingComparison }}
              </p>
            </section>

            <section
              class="civic-current-measure civic-current-measure--homicides"
              aria-labelledby="current-homicides"
            >
              <h3 id="current-homicides" class="civic-stat-label">
                PPD homicides
              </h3>
              <p class="civic-current-through">
                Through
                <time :datetime="stats.homicides_data_through">
                  {{ formatDate(stats.homicides_data_through) }}
                </time>
              </p>
              <p class="civic-stat-total">
                {{ formatNumber(stats.homicides_ytd) }}
              </p>
              <p v-if="homicideComparison" class="civic-current-comparison">
                {{ homicideComparison }}
              </p>
            </section>
          </div>
          <p class="civic-current-context">
            PPD homicide statistics count all homicides citywide, whether or not
            a gun was involved. The two measures can overlap, so they should not
            be added.
          </p>
        </section>

        <section
          class="civic-rule-section civic-stats-section"
          aria-labelledby="counts-by-year"
        >
          <div class="civic-annual-heading">
            <div class="civic-annual-heading__title-row">
              <h2 id="counts-by-year">Counts by year</h2>
              <button
                class="usa-button usa-button--outline civic-print-button"
                type="button"
                aria-label="Print counts by year"
                title="Print counts by year"
                @click="printCountsByYear"
              >
                <svg
                  aria-hidden="true"
                  focusable="false"
                  viewBox="0 0 24 24"
                >
                  <path
                    d="M18 8H6V3h12v5Zm0 9v4H6v-4h12Zm1-7c1.66 0 3 1.34 3 3v4h-2v-2H4v2H2v-4c0-1.66 1.34-3 3-3h14Zm-2-5H7v3h10V5Zm-1 14v-2H8v2h8Z"
                  />
                </svg>
                <span class="civic-print-button__label">Print counts by year</span>
              </button>
            </div>
            <p class="civic-annual-heading__description">
              Bars show shooting-victim counts. The PPD homicide column lists
              exact totals. The {{ stats.current_year }} row is year to date,
              with a separate reporting date for each source.
            </p>
          </div>

          <div class="civic-annual-series">
            <div
              class="usa-table-container--scrollable civic-table-region"
              role="region"
              aria-labelledby="counts-by-year"
              tabindex="0"
            >
              <table
                class="usa-table usa-table--compact usa-table--borderless civic-table civic-annual-table"
              >
                <caption class="usa-sr-only">
                  Philadelphia shooting-victim records and PPD homicide totals
                  by year. Bars visually encode shooting-victim counts; exact
                  values are shown for both measures.
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Year</th>
                    <th scope="col">Shooting victims</th>
                    <th scope="col">PPD homicides</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="year in annualRows"
                    :key="year.year"
                    :class="{
                      'civic-annual-row--current':
                        year.year === stats.current_year,
                    }"
                  >
                    <th scope="row">
                      <span>{{ year.year }}</span>
                      <span
                        v-if="year.year === stats.current_year"
                        class="civic-annual-ytd"
                      >
                        Year to date
                      </span>
                    </th>
                    <td class="civic-annual-victims">
                      <div class="civic-annual-measure">
                        <span class="civic-annual-value">
                          {{ formatNumber(year.victims) }}
                        </span>
                        <span
                          class="civic-annual-bar-plot"
                          aria-hidden="true"
                        >
                          <span
                            class="civic-annual-bar"
                            :style="annualBarStyle(year.victims, peakVictimCount)"
                          />
                        </span>
                        <span
                          v-if="year.year === stats.current_year"
                          class="civic-annual-current-date civic-annual-current-date--victims"
                        >
                          through
                          <time :datetime="stats.shootings_data_through">
                            {{ formatDate(stats.shootings_data_through) }}
                          </time>
                        </span>
                      </div>
                    </td>
                    <td class="civic-annual-homicides">
                      <div class="civic-annual-homicide-measure">
                        <span class="civic-annual-value">
                          {{ formatNumber(year.homicides) }}
                        </span>
                        <span
                          v-if="year.year === stats.current_year"
                          class="civic-annual-current-date civic-annual-current-date--homicides"
                        >
                          through
                          <time :datetime="stats.homicides_data_through">
                            {{ formatDate(stats.homicides_data_through) }}
                          </time>
                        </span>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="civic-annual-sources">
              <p class="civic-annual-source">
                Shooting victims:
                <a
                  href="https://opendataphilly.org/datasets/shooting-victims/"
                  rel="external"
                >Philadelphia Police Department shooting-victim records</a
                > via OpenDataPhilly.
              </p>
              <p class="civic-annual-source">
                Homicides:
                <a
                  href="https://www.phillypolice.com/crime-data/crime-statistics/"
                  rel="external"
                >Philadelphia Police Department homicide statistics</a
                >.
              </p>
            </div>
          </div>
        </section>
      </template>

      <section
        v-else
        class="usa-summary-box civic-summary-box civic-stats-error"
        aria-labelledby="statistics-unavailable"
        aria-live="polite"
      >
        <div class="usa-summary-box__body">
          <h2 id="statistics-unavailable" class="usa-summary-box__heading">
            Current statistics are temporarily unavailable
          </h2>
          <div class="usa-summary-box__text">
            <p>
              You can still use the <NuxtLink to="/data">Data</NuxtLink> and
              <NuxtLink to="/methodology">Methodology</NuxtLink> pages. Missing
              values are not treated as zero.
            </p>
            <button
              class="usa-button"
              type="button"
              :disabled="status === 'pending'"
              @click="refresh"
            >
              {{ status === "pending" ? "Trying again…" : "Try again" }}
            </button>
            <p v-if="statsError" class="civic-stat-note">
              The statistics service did not respond to this request.
            </p>
          </div>
        </div>
      </section>

      <nav
        class="civic-rule-section civic-stats-section civic-stats-reading-note"
        aria-label="Statistics documentation"
      >
        <ul class="usa-list usa-list--unstyled civic-source-links">
          <li><NuxtLink to="/data">Data access and field guide</NuxtLink></li>
          <li><NuxtLink to="/methodology">Methodology and limitations</NuxtLink></li>
        </ul>
      </nav>
    </div>
  </main>
</template>

<style scoped>
.civic-page-intro {
  border-bottom: 0;
}

.civic-stats-current--compact {
  padding-bottom: 0;
}

.civic-stats-current--compact > h2 {
  margin-bottom: 1rem;
}

.civic-stats-current--compact > h2,
.civic-stats-section h2 {
  font-weight: 600;
}

.civic-stats-current__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 2rem clamp(2rem, 6vw, 5rem);
  margin: 0;
  padding: 0;
  border-top: 0;
  border-bottom: 0;
}

.civic-current-measure {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 0;
}

.civic-current-measure > h3.civic-stat-label {
  font-weight: 600;
}

.civic-stats-current--compact .civic-current-measure--homicides {
  padding-left: 0;
}

.civic-stats-current--compact .civic-stat-total {
  margin: 0.55rem 0 0;
  font-size: clamp(3rem, 5.5vw, 3.75rem);
  font-weight: 600;
}

.civic-stats-current--compact .civic-outcome-list {
  gap: 1rem 1.75rem;
  margin-top: 0.65rem;
  padding-top: 0;
  border-top: 0;
  flex-wrap: wrap;
}

.civic-stats-current--compact .civic-outcome-list dd {
  font-size: 1.3rem;
}

.civic-current-through {
  margin: 0.2rem 0 0;
  color: var(--civic-color-ink-subtle);
  font-size: 0.9rem;
  line-height: 1.4;
}

.civic-current-comparison {
  max-width: 27rem;
  margin: 0.75rem 0 0;
  color: var(--civic-color-ink);
  font-size: 1rem;
  line-height: 1.5;
}

.civic-current-context {
  max-width: 58rem;
  margin: 1.5rem 0 0;
  color: var(--civic-color-ink-muted);
  font-size: 0.95rem;
  line-height: 1.55;
}

.civic-stats-section {
  padding-top: 0;
  border-top: 0;
}

.civic-annual-heading {
  min-width: 0;
}

.civic-annual-heading__title-row {
  display: flex;
  gap: 1.5rem;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
}

.civic-annual-heading__title-row h2 {
  margin: 0;
}

.civic-annual-heading__description {
  max-width: var(--civic-content-measure);
  margin: 0.65rem 0 0;
  color: var(--civic-color-ink-muted);
  line-height: 1.7;
}

.civic-print-button {
  display: inline-flex;
  flex: none;
  gap: 0.45rem;
  align-items: center;
  margin: 0;
  min-height: 2.75rem;
  padding: 0.65rem 0.85rem;
  font-size: 0.88rem;
  white-space: nowrap;
}

.civic-print-button svg {
  width: 1.05rem;
  height: 1.05rem;
  fill: currentColor;
}

.civic-annual-series {
  margin-top: 2rem;
  min-width: 0;
}

.civic-annual-series .civic-table-region,
.civic-annual-table {
  width: 100%;
  max-width: none;
}

.civic-annual-table {
  table-layout: fixed;
}

.civic-annual-table th,
.civic-annual-table td {
  padding: 0.48rem 0.3rem;
  border: 0;
  vertical-align: middle;
  white-space: normal;
}

.civic-annual-table thead th {
  padding-bottom: 0.6rem;
  border-bottom: 1px solid var(--civic-color-rule);
  font-size: 0.9rem;
}

.civic-annual-table thead th:first-child {
  width: 7.5rem;
}

.civic-annual-table thead th:last-child {
  width: 11rem;
  text-align: right;
}

.civic-annual-table tbody th {
  font-size: 0.9rem;
  font-weight: 400;
  font-variant-numeric: tabular-nums;
}

.civic-annual-table tbody tr:first-child {
  font-weight: 400;
}

.civic-annual-measure {
  display: grid;
  grid-template-columns: 4.25rem minmax(3rem, 1fr);
  gap: 0.65rem;
  align-items: center;
}

.civic-annual-value {
  color: var(--civic-color-ink-muted);
  font-size: 0.9rem;
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.civic-annual-homicides {
  text-align: right;
}

.civic-annual-homicide-measure {
  display: grid;
  gap: 0.65rem;
  justify-items: end;
}

.civic-annual-homicides .civic-annual-value {
  display: block;
}

.civic-annual-bar-plot {
  display: block;
  height: 0.46rem;
}

.civic-annual-bar {
  display: block;
  min-width: 0.14rem;
  height: 100%;
  background: #7698aa;
}

.civic-annual-row--current {
  border-top: 1.5px solid var(--civic-color-rule);
}

.civic-annual-row--current th,
.civic-annual-row--current td {
  padding-top: 0.75rem;
}

.civic-annual-row--current .civic-annual-bar {
  background: var(--civic-color-ink-muted);
}

.civic-annual-ytd,
.civic-annual-current-date {
  display: block;
  color: var(--civic-color-ink-subtle);
  font-weight: 400;
  white-space: normal;
}

.civic-annual-ytd {
  margin-top: 0.15rem;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.civic-annual-current-date {
  grid-column: 1 / -1;
  margin-top: 0.1rem;
  font-size: 0.75rem;
  line-height: 1.3;
}

.civic-annual-current-date--victims {
  justify-self: start;
  text-align: left;
}

.civic-annual-current-date--homicides {
  text-align: right;
}

.civic-annual-source {
  margin: 0;
  color: var(--civic-color-ink-subtle);
  font-size: 0.82rem;
  line-height: 1.45;
}

.civic-annual-sources {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.35rem 1.5rem;
  margin-top: 0.85rem;
}

.civic-annual-source strong {
  font-weight: 600;
}

.civic-stats-reading-note .civic-source-links {
  display: flex;
  gap: 0.5rem 1.5rem;
  margin-top: 0;
  margin-bottom: 0;
  padding-left: 0;
  flex-wrap: wrap;
}

@media (max-width: 39.99em) {
  .civic-stats-current__grid {
    grid-template-columns: 1fr;
    gap: 2rem;
  }

  .civic-current-measure {
    padding-right: 0;
  }

  .civic-stats-current--compact .civic-current-measure--homicides {
    padding: 0;
    border-top: 0;
    border-left: 0;
  }

  .civic-annual-heading {
    min-width: 0;
  }

  .civic-annual-heading__title-row {
    align-items: center;
    gap: 1rem;
  }

  .civic-annual-heading__title-row h2 {
    flex: 1;
  }

  .civic-print-button {
    width: 2.75rem;
    min-width: 2.75rem;
    height: 2.75rem;
    margin: 0;
    padding: 0;
    justify-content: center;
  }

  .civic-print-button__label {
    display: none;
  }

  .civic-annual-table thead th:first-child {
    width: 5.25rem;
  }

  .civic-annual-table thead th:last-child {
    width: 6.5rem;
  }

  .civic-annual-measure {
    grid-template-columns: 3.75rem minmax(2.5rem, 1fr);
    gap: 0.5rem;
  }

  .civic-annual-sources {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 30em) {
  .civic-annual-measure {
    grid-template-columns: 3rem minmax(1.5rem, 1fr);
    gap: 0.3rem;
  }

  .civic-annual-bar-plot {
    min-width: 0;
  }
}

@media print {
  :global(html),
  :global(body),
  :global(#__nuxt),
  :global(.civic-app-shell),
  .civic-reference-page {
    display: block !important;
    width: auto !important;
    height: auto !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: visible !important;
    color: #1b1b1b !important;
    background: #fff !important;
  }

  :global(.civic-app-shell > main) {
    flex: none !important;
  }

  :global(.usa-skipnav),
  :global(.civic-site-header),
  :global(.civic-site-footer),
  .civic-print-button,
  .civic-stats-current,
  .civic-stats-reading-note,
  .civic-stats-error,
  .civic-page-intro .usa-intro {
    display: none !important;
  }

  .civic-page-intro,
  .civic-content-section {
    width: 100% !important;
    max-width: none !important;
    margin: 0 !important;
    padding: 0 !important;
  }

  .civic-page-intro {
    padding-bottom: 0.08in !important;
  }

  .civic-page-intro h1 {
    margin: 0 !important;
    font-size: 18pt !important;
    line-height: 1.15 !important;
  }

  .civic-page-intro h1,
  .civic-page-intro p,
  .civic-stats-section h2,
  .civic-annual-table th,
  .civic-annual-table td,
  .civic-annual-value,
  .civic-annual-source,
  .civic-annual-source a {
    color: #1b1b1b !important;
  }

  .civic-annual-heading__description,
  .civic-annual-ytd,
  .civic-annual-current-date {
    color: #3d4551 !important;
  }

  .civic-stats-section {
    margin: 0 !important;
    padding: 0 !important;
    border: 0 !important;
    break-inside: auto;
    page-break-inside: auto;
  }

  .civic-stats-section h2 {
    font-size: 13pt !important;
    line-height: 1.2 !important;
  }

  .civic-annual-heading__description {
    margin-top: 0.035in;
    font-size: 8.5pt;
    line-height: 1.25;
  }

  .civic-annual-series {
    margin-top: 0.06in;
    break-inside: auto;
    page-break-inside: auto;
  }

  .civic-annual-table tr,
  .civic-annual-sources {
    break-inside: avoid-page;
    page-break-inside: avoid;
  }

  .civic-annual-series .civic-table-region {
    overflow: visible !important;
  }

  .civic-annual-table th,
  .civic-annual-table td {
    padding: 0.035in 0.04in;
    font-size: 8pt !important;
    line-height: 1.15 !important;
  }

  .civic-annual-table thead th {
    padding-bottom: 0.045in;
    font-size: 8pt !important;
  }

  .civic-annual-table thead th:first-child {
    width: 0.75in;
  }

  .civic-annual-table thead th:last-child {
    width: 1.25in;
  }

  .civic-annual-row--current th,
  .civic-annual-row--current td {
    padding-top: 0.055in;
  }

  .civic-annual-measure {
    display: grid;
    grid-template-columns: 0.55in minmax(0.5in, 1fr);
    gap: 0.08in;
  }

  .civic-annual-value {
    font-size: 8pt !important;
  }

  .civic-annual-bar-plot {
    display: block;
    height: 0.055in;
  }

  .civic-annual-ytd,
  .civic-annual-current-date {
    font-size: 6.5pt !important;
    line-height: 1.15 !important;
  }

  .civic-annual-sources {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    margin-top: 0.04in;
    gap: 0.02in 0.3in;
    break-before: avoid-page;
    page-break-before: avoid;
  }

  .civic-annual-source {
    font-size: 7.5pt !important;
    line-height: 1.2 !important;
  }

  .civic-annual-bar {
    display: block;
    background: #52778a !important;
    print-color-adjust: exact;
    -webkit-print-color-adjust: exact;
  }
}
</style>
