<template>
  <div class="about-page-wrapper">
    <app-navbar :show-overlay="false" :show-back-button="true" />

    <main class="about-page">
      <!-- Hero -->
      <header class="hero-section">
        <p class="hero-kicker">About this dashboard</p>
        <h1 class="hero-title">Philadelphia Gun Violence Dashboard</h1>
        <p class="hero-subtitle">
          An open-source, interactive visualization of shooting incidents in
          Philadelphia, <span class="accent-date">updated daily</span> with
          public data.
        </p>
      </header>

      <!-- Meta strip -->
      <div class="meta-strip">
        <div class="meta-cell">
          <div class="meta-label">Data through</div>
          <div class="meta-value">
            {{ formatDateLong(meta?.shootings?.data_through) }}
          </div>
        </div>
        <div class="meta-cell">
          <div class="meta-label">Update cadence</div>
          <div class="meta-value">Daily, automated</div>
        </div>
        <div class="meta-cell">
          <div class="meta-label">Records since 2015</div>
          <div class="meta-value">{{ recordsValue }}</div>
        </div>
      </div>

      <!-- 01 Background -->
      <section class="cr-section">
        <div class="cr-label">
          <span class="cr-num">01</span>
          <h2 class="cr-title">Background</h2>
        </div>
        <div class="cr-content">
          <p>
            <a
              href="https://nickhand.dev"
              target="_blank"
              rel="noopener noreferrer"
              class="text-link"
              @click="trackExternalLink('Nick Hand', 'https://nickhand.dev')"
              >Nick Hand</a
            >
            built the first version of this dashboard while serving as
            Director of Finance, Policy, and Data at the Philadelphia City
            Controller's Office. The goal was to give the public a clear view
            of gun violence trends as violence rose to crisis levels.
          </p>
          <p>
            He has kept the dashboard going as an independent project since
            leaving the Controller's Office. He rebuilt it with modern web
            tools, new features, and better accessibility.
          </p>
        </div>
      </section>

      <!-- 02 Data sources -->
      <section class="cr-section">
        <div class="cr-label">
          <span class="cr-num">02</span>
          <h2 class="cr-title">Data sources</h2>
        </div>
        <div class="cr-content">
          <p>
            All data is publicly available from the City of Philadelphia and
            Pennsylvania's Unified Judicial System.
          </p>
          <div class="source-register">
            <div class="source-row">
              <div>
                <h3 class="source-name">Shooting victims</h3>
                <p class="source-desc">
                  Individual-level records of shooting incidents from the City's
                  open data program, updated daily.
                </p>
              </div>
              <a
                href="https://www.opendataphilly.org/dataset/shooting-victims"
                target="_blank"
                rel="noopener noreferrer"
                class="source-link"
                @click="
                  trackExternalLink(
                    'Shooting Victims',
                    'https://www.opendataphilly.org/dataset/shooting-victims'
                  )
                "
                >OpenDataPhilly.org <span aria-hidden="true">↗</span></a
              >
            </div>
            <div class="source-row">
              <div>
                <h3 class="source-name">Homicide statistics</h3>
                <p class="source-desc">
                  Official homicide counts from the Philadelphia Police
                  Department's statistics unit.
                </p>
              </div>
              <a
                href="https://www.phillypolice.com/crime-data/crime-statistics/#homicide_numbers"
                target="_blank"
                rel="noopener noreferrer"
                class="source-link"
                @click="
                  trackExternalLink(
                    'Homicide Statistics',
                    'https://www.phillypolice.com/crime-data/crime-statistics/#homicide_numbers'
                  )
                "
                >PhillyPolice.com <span aria-hidden="true">↗</span></a
              >
            </div>
            <div class="source-row">
              <div>
                <h3 class="source-name">Public court records</h3>
                <p class="source-desc">
                  Court dockets linked to incidents by police DC number through
                  Pennsylvania's Unified Judicial System.
                </p>
              </div>
              <a
                href="https://ujsportal.pacourts.us/CaseSearch"
                target="_blank"
                rel="noopener noreferrer"
                class="source-link"
                @click="
                  trackExternalLink(
                    'Court Records',
                    'https://ujsportal.pacourts.us/CaseSearch'
                  )
                "
                >PA Courts Portal <span aria-hidden="true">↗</span></a
              >
            </div>
          </div>
        </div>
      </section>

      <!-- 03 Data currency -->
      <section class="cr-section">
        <div class="cr-label">
          <span class="cr-num">03</span>
          <h2 class="cr-title">Data currency</h2>
        </div>
        <div class="cr-content">
          <p class="stats-page-note">
            For the latest numbers and common questions, see the
            <a :href="statsPageUrl" class="text-link">statistics summary page</a
            >.
          </p>
          <div v-if="metaLoading" class="currency-status" role="status">
            Loading data freshness…
          </div>
          <div v-else-if="metaError" class="currency-status currency-error">
            Unable to load data freshness information
          </div>
          <div v-else class="currency-grid">
            <div class="currency-cell">
              <div class="currency-label">Shooting victims</div>
              <div class="currency-date">
                {{ formatDate(meta?.shootings?.data_through) }}
              </div>
              <div class="currency-updated">
                Updated {{ formatRelativeTime(meta?.shootings?.last_updated) }}
              </div>
            </div>
            <div class="currency-cell">
              <div class="currency-label">Homicide statistics</div>
              <div class="currency-date">
                {{ formatDate(meta?.homicides?.data_through) }}
              </div>
              <div class="currency-updated">
                Updated {{ formatRelativeTime(meta?.homicides?.last_updated) }}
              </div>
            </div>
            <div class="currency-cell">
              <div class="currency-label">Court records</div>
              <div class="currency-date">
                {{ formatDate(meta?.courts?.data_through) }}
              </div>
              <div class="currency-updated">
                Updated {{ formatRelativeTime(meta?.courts?.last_updated) }}
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 04 Methodology & limitations -->
      <section class="cr-section">
        <div class="cr-label">
          <span class="cr-num">04</span>
          <h2 class="cr-title">Methodology &amp; limitations</h2>
        </div>
        <div class="cr-content">
          <div class="def-row">
            <h3 class="def-label">Data updates</h3>
            <p class="def-value">
              Shooting victim data is updated daily through automated
              pipelines. PPD's statistics unit enters data from detective
              reports, usually by 10:30 AM on weekdays.
            </p>
          </div>
          <div class="def-row">
            <h3 class="def-label">Officer-involved shootings</h3>
            <p class="def-value">
              This dashboard only includes criminal shooting victims.
              Officer-involved shootings are left out because they are reported
              with different fields. See
              <a
                href="https://www.phillypolice.com/ois"
                target="_blank"
                rel="noopener noreferrer"
                class="text-link"
                @click="
                  trackExternalLink(
                    'Officer-Involved Shootings',
                    'https://www.phillypolice.com/ois'
                  )
                "
                >PPD's website</a
              >
              for that data.
            </p>
          </div>
          <div class="def-row">
            <h3 class="def-label">Court case linkage</h3>
            <p class="def-value">
              Court records are refreshed weekly by searching each incident's
              police DC number in the state's public portal.
            </p>
          </div>
          <div class="def-row">
            <h3 class="def-label">Homicide counts</h3>
            <p class="def-value">
              PPD homicide totals include all homicides, not just gun deaths.
              Fatal shootings here may undercount total gun homicides.
            </p>
          </div>
          <div class="def-row">
            <h3 class="def-label">Data accuracy</h3>
            <p class="def-value">
              All data is preliminary and may differ from other official
              sources. This tool is for information only and should not be the
              only source for research or policy decisions.
            </p>
          </div>
        </div>
      </section>

      <!-- 05 Open source -->
      <section class="cr-section">
        <div class="cr-label">
          <span class="cr-num">05</span>
          <h2 class="cr-title">Open source</h2>
        </div>
        <div class="cr-content">
          <p>
            The frontend is built with Vue 3, TypeScript, and MapLibre GL. The
            backend uses FastAPI and automated Python ETL pipelines. The
            complete codebase is public. Anyone can explore it, learn from it,
            or contribute.
          </p>
          <a
            href="https://github.com/nickhand/philly-gun-violence-dashboard"
            target="_blank"
            rel="noopener noreferrer"
            class="repo-link"
            @click="
              trackExternalLink(
                'GitHub Repository',
                'https://github.com/nickhand/philly-gun-violence-dashboard'
              )
            "
            >View the repository on GitHub <span aria-hidden="true">↗</span></a
          >
        </div>
      </section>

      <!-- 06 Contact -->
      <section class="cr-section">
        <div class="cr-label">
          <span class="cr-num">06</span>
          <h2 class="cr-title">Contact</h2>
        </div>
        <div class="cr-content">
          <p>
            Corrections, suggestions, and ideas for working together are
            welcome.
          </p>
          <div class="def-row contact-row">
            <div class="contact-label">Email</div>
            <a
              href="mailto:nicholas.adam.hand@gmail.com"
              class="contact-link"
              @click="
                trackExternalLink(
                  'Email',
                  'mailto:nicholas.adam.hand@gmail.com'
                )
              "
              >nicholas.adam.hand@gmail.com</a
            >
          </div>
          <div class="def-row contact-row">
            <div class="contact-label">Web</div>
            <a
              href="https://nickhand.dev"
              target="_blank"
              rel="noopener noreferrer"
              class="contact-link"
              @click="trackExternalLink('Website', 'https://nickhand.dev')"
              >nickhand.dev</a
            >
          </div>
        </div>
      </section>
    </main>

    <!-- Footer -->
    <app-footer />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useHead } from "@unhead/vue";
import AppNavbar from "@/app/components/AppNavbar.vue";
import AppFooter from "@/app/components/AppFooter.vue";
import { fetchAllMeta, type AllDatasetsMeta } from "@/shared/api/meta";
import { track } from "@/shared/analytics";

/**
 * Track clicks on external links.
 */
function trackExternalLink(label: string, url: string): void {
  track("external_link_clicked", { label, url });
}

// The stats page is server-rendered by the API and proxied through Netlify
// (outside the SPA router), so use a full-page navigation under the app base.
const statsPageUrl = `${import.meta.env.BASE_URL}stats`;

// Data freshness state
const meta = ref<AllDatasetsMeta | null>(null);
const metaLoading = ref(true);
const metaError = ref(false);

/**
 * Format a date string (YYYY-MM-DD) to a human-readable format.
 */
function formatDate(dateStr: string | undefined): string {
  if (!dateStr) return "—";
  const date = new Date(dateStr + "T00:00:00");
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/**
 * Format a date string (YYYY-MM-DD) with the full month name, for the
 * meta strip (e.g. "August 4, 2026").
 */
function formatDateLong(dateStr: string | undefined): string {
  if (!dateStr) return "—";
  const date = new Date(dateStr + "T00:00:00");
  return date.toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

/**
 * Meta-strip value for total records, e.g. "17,669 victims".
 */
const recordsValue = computed(() => {
  const count = meta.value?.shootings?.row_count;
  return typeof count === "number"
    ? `${count.toLocaleString("en-US")} victims`
    : "—";
});

/**
 * Format an ISO timestamp to a relative time string (e.g., "2 hours ago").
 */
function formatRelativeTime(isoStr: string | undefined): string {
  if (!isoStr) return "—";
  const date = new Date(isoStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return "just now";
  if (diffMins < 60)
    return `${diffMins} minute${diffMins !== 1 ? "s" : ""} ago`;
  if (diffHours < 24)
    return `${diffHours} hour${diffHours !== 1 ? "s" : ""} ago`;
  if (diffDays === 1) return "yesterday";
  if (diffDays < 7) return `${diffDays} days ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// Fetch metadata on mount
onMounted(async () => {
  try {
    meta.value = await fetchAllMeta();
  } catch (err) {
    console.error("Failed to fetch data freshness metadata:", err);
    metaError.value = true;
  } finally {
    metaLoading.value = false;
  }
});

// SEO Meta Tags for About Page
useHead({
  title: "About | Philadelphia Gun Violence Dashboard",
  meta: [
    {
      name: "description",
      content:
        "Learn about the Philadelphia Gun Violence Dashboard, an open-source project that maps shooting incidents with public data updated daily. Built with Vue 3, FastAPI, and MapLibre.",
    },
  ],
  link: [
    {
      rel: "canonical",
      href: "https://www.nickhand.dev/philly-gun-violence-map/about",
    },
  ],
});
</script>

<style scoped>
.about-page-wrapper {
  background-color: #353d42;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
}

.about-page {
  flex: 1;
  max-width: 860px;
  width: 100%;
  margin: 0 auto;
  padding: 0 44px;
}

/* Hero */
.hero-section {
  text-align: center;
  padding: 44px 0 36px;
}

.hero-kicker {
  font-family: var(--heading-font-family);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.24em;
  text-transform: uppercase;
  color: #b2beb5;
  margin: 0 0 14px;
}

.hero-title {
  font-family: var(--heading-font-family);
  font-size: 40px;
  font-weight: 500;
  line-height: 1.15;
  color: #ffffff;
  margin: 0 0 16px;
}

.hero-subtitle {
  font-family: var(--heading-font-family);
  font-weight: 300;
  font-size: 19px;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.8);
  max-width: 600px;
  margin: 0 auto;
}

.accent-date {
  color: #b2beb5;
}

/* Meta strip */
.meta-strip {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  border-top: 1px solid rgba(255, 255, 255, 0.12);
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
  padding: 16px 0;
  margin-bottom: 44px;
}

.meta-cell {
  text-align: center;
  border-left: 1px solid rgba(255, 255, 255, 0.1);
}

.meta-cell:first-child {
  border-left: none;
}

.meta-label {
  font-size: 10.5px;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.45);
  margin-bottom: 6px;
}

.meta-value {
  font-size: 14.5px;
  color: #ffffff;
  font-variant-numeric: tabular-nums;
}

/* Numbered sections */
.cr-section {
  border-top: 1px solid rgba(255, 255, 255, 0.12);
  padding: 26px 0 38px;
  display: grid;
  grid-template-columns: 190px 1fr;
  gap: 32px;
}

.cr-num {
  display: block;
  font-family: var(--heading-font-family);
  font-size: 11px;
  letter-spacing: 0.1em;
  color: #b2beb5;
  margin-bottom: 6px;
}

.cr-title {
  font-family: var(--heading-font-family);
  font-size: 15px;
  font-weight: 600;
  color: #ffffff;
  margin: 0;
  line-height: 1.4;
}

.cr-content {
  color: rgba(255, 255, 255, 0.8);
  font-size: 14.5px;
  line-height: 1.7;
  min-width: 0;
}

.cr-content > p {
  margin: 0 0 16px;
}

.cr-content > p:last-child {
  margin-bottom: 0;
}

/* Text links */
.text-link {
  color: #7ab5e5;
  text-decoration: none;
  transition: color 0.2s;
}

.text-link:hover {
  color: #9ecbf0;
  text-decoration: underline;
}

/* 02 Source register */
.source-register {
  margin-top: 8px;
}

.source-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 24px;
  align-items: baseline;
  padding: 16px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.09);
}

.source-row:last-child {
  border-bottom: none;
}

.source-name {
  font-family: var(--heading-font-family);
  font-size: 14.5px;
  font-weight: 600;
  color: #ffffff;
  margin: 0 0 6px;
}

.source-desc {
  font-size: 13.5px;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.62);
  margin: 0;
}

.source-link {
  font-size: 11.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #7ab5e5;
  text-decoration: none;
  white-space: nowrap;
  transition: color 0.2s;
}

.source-link:hover {
  color: #9ecbf0;
  text-decoration: underline;
}

/* 03 Data currency */
.stats-page-note {
  font-size: 13.5px;
  color: rgba(255, 255, 255, 0.62);
}

.currency-status {
  font-size: 13.5px;
  color: rgba(255, 255, 255, 0.62);
  padding: 12px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.09);
}

.currency-error {
  color: #ff8a8a;
}

.currency-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  margin-top: 8px;
}

.currency-cell {
  border-top: 2px solid rgba(255, 255, 255, 0.3);
  padding-top: 12px;
}

.currency-label {
  font-size: 10.5px;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.45);
  margin-bottom: 8px;
}

.currency-date {
  font-family: var(--heading-font-family);
  font-size: 18px;
  font-weight: 500;
  color: #ffffff;
  font-variant-numeric: tabular-nums;
  margin-bottom: 4px;
}

.currency-updated {
  font-size: 12px;
  color: #b2beb5;
}

/* 04 / 06 Definition rows */
.def-row {
  display: grid;
  grid-template-columns: 190px 1fr;
  gap: 16px;
  padding: 13px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.09);
}

.def-row:last-child {
  border-bottom: none;
}

.def-label {
  font-family: var(--heading-font-family);
  font-size: 13.5px;
  font-weight: 600;
  color: #ffffff;
  margin: 0;
  line-height: 1.6;
}

.def-value {
  font-size: 13.5px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.7);
  margin: 0;
}

/* 05 Repo link */
.repo-link {
  display: inline-block;
  font-size: 13.5px;
  color: #7ab5e5;
  text-decoration: none;
  border-bottom: 1px solid rgba(122, 181, 229, 0.5);
  padding-bottom: 2px;
  transition: color 0.2s;
}

.repo-link:hover {
  color: #9ecbf0;
}

/* 06 Contact rows */
.contact-row {
  align-items: baseline;
}

.contact-label {
  font-size: 10.5px;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.45);
}

.contact-link {
  font-size: 14px;
  color: #7ab5e5;
  text-decoration: none;
  transition: color 0.2s;
  justify-self: start;
}

.contact-link:hover {
  color: #9ecbf0;
  text-decoration: underline;
}

/* Responsive */
@media (max-width: 768px) {
  .hero-title {
    font-size: 28px;
  }

  .hero-subtitle {
    font-size: 16px;
  }

  .cr-section {
    grid-template-columns: 1fr;
    gap: 16px;
  }

  .meta-strip {
    grid-template-columns: 1fr;
    gap: 16px;
  }

  .meta-cell {
    border-left: none;
    border-top: 1px solid rgba(255, 255, 255, 0.12);
    padding-top: 12px;
  }

  .meta-cell:first-child {
    border-top: none;
    padding-top: 0;
  }

  .currency-grid {
    grid-template-columns: 1fr;
  }

  .source-row {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .def-row {
    grid-template-columns: 1fr;
    gap: 4px;
  }
}

@media (max-width: 480px) {
  .about-page {
    padding: 0 20px;
  }
}
</style>
