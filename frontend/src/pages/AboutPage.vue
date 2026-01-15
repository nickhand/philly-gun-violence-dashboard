<template>
  <div class="about-page-wrapper">
    <app-navbar :show-overlay="false" :show-back-button="true" />

    <main class="about-page">
      <!-- Hero Section -->
      <header class="hero-section">
        <h1 class="hero-title">Philadelphia Gun Violence Dashboard</h1>
        <p class="hero-subtitle">
          An open-source, interactive visualization of shooting incidents in
          Philadelphia, updated daily with public data.
        </p>
      </header>

      <!-- Project Background -->
      <section class="content-section">
        <div class="section-header">
          <div class="section-icon">
            <v-icon icon="mdi-information-outline" size="24" />
          </div>
          <h2 class="section-title">About This Project</h2>
        </div>
        <div class="section-content">
          <p>
            This dashboard was originally developed by
            <a
              href="https://nickhand.dev"
              target="_blank"
              rel="noopener noreferrer"
              class="text-link"
              @click="trackExternalLink('Nick Hand', 'https://nickhand.dev')"
              >Nick Hand</a
            >
            while serving as Director of Finance, Policy, and Data at the
            Philadelphia City Controller's Office. The project was created to
            provide transparent, accessible insights into gun violence trends
            across the city, during a time when gun violence was spiking to
            crisis levels.
          </p>
          <p>
            Since leaving the Controller's Office, I have continued to maintain
            the dashboard as an independent project and have completely rebuilt
            it with modern web technologies, new features, and enhanced
            accessibility.
          </p>
        </div>
      </section>

      <!-- Data Sources -->
      <section class="content-section">
        <div class="section-header">
          <div class="section-icon">
            <v-icon icon="mdi-database-outline" size="24" />
          </div>
          <h2 class="section-title">Data Sources</h2>
        </div>
        <div class="section-content">
          <p>
            This dashboard relies on publicly available data from the City of
            Philadelphia and Pennsylvania's Unified Judicial System:
          </p>
          <div class="data-sources">
            <a
              href="https://www.opendataphilly.org/dataset/shooting-victims"
              target="_blank"
              rel="noopener noreferrer"
              class="data-source-card"
              @click="
                trackExternalLink(
                  'Shooting Victims',
                  'https://www.opendataphilly.org/dataset/shooting-victims'
                )
              "
            >
              <div class="source-header">Shooting Victims</div>
              <p>
                Individual-level data on shooting incidents from the City's open
                data program, updated daily.
              </p>
              <span class="source-origin">OpenDataPhilly.org</span>
            </a>

            <a
              href="https://www.phillypolice.com/crime-data/crime-statistics/#homicide_numbers"
              target="_blank"
              rel="noopener noreferrer"
              class="data-source-card"
              @click="
                trackExternalLink(
                  'Homicide Statistics',
                  'https://www.phillypolice.com/crime-data/crime-statistics/#homicide_numbers'
                )
              "
            >
              <div class="source-header">Homicide Statistics</div>
              <p>
                Official homicide counts from the Philadelphia Police
                Department's (PPD's) statistics unit.
              </p>
              <span class="source-origin">PhillyPolice.com</span>
            </a>

            <a
              href="https://ujsportal.pacourts.us/CaseSearch"
              target="_blank"
              rel="noopener noreferrer"
              class="data-source-card"
              @click="
                trackExternalLink(
                  'Court Records',
                  'https://ujsportal.pacourts.us/CaseSearch'
                )
              "
            >
              <div class="source-header">Public Court Records</div>
              <p>
                Public court records linked via DC number from Pennsylvania's
                Unified Judicial System portal.
              </p>
              <span class="source-origin">PA Courts Portal</span>
            </a>
          </div>
        </div>
      </section>

      <!-- Data Freshness -->
      <section class="content-section">
        <div class="section-header">
          <div class="section-icon">
            <v-icon icon="mdi-update" size="24" />
          </div>
          <h2 class="section-title">Data Freshness</h2>
        </div>
        <div class="section-content">
          <p>
            Data is automatically updated via scheduled ETL pipelines. The dates
            below indicate the most recent data included in each dataset:
          </p>
          <div v-if="metaLoading" class="freshness-loading">
            <v-progress-circular indeterminate size="20" width="2" />
            <span>Loading data freshness...</span>
          </div>
          <div v-else-if="metaError" class="freshness-error">
            <v-icon icon="mdi-alert-circle-outline" size="18" />
            <span>Unable to load data freshness information</span>
          </div>
          <div v-else class="freshness-grid">
            <div class="freshness-item">
              <div class="freshness-label">Shooting Victims</div>
              <div class="freshness-value">
                <span class="freshness-date">{{
                  formatDate(meta?.shootings?.data_through)
                }}</span>
                <span class="freshness-updated"
                  >Updated
                  {{ formatRelativeTime(meta?.shootings?.last_updated) }}</span
                >
              </div>
            </div>
            <div class="freshness-item">
              <div class="freshness-label">Homicide Statistics</div>
              <div class="freshness-value">
                <span class="freshness-date">{{
                  formatDate(meta?.homicides?.data_through)
                }}</span>
                <span class="freshness-updated"
                  >Updated
                  {{ formatRelativeTime(meta?.homicides?.last_updated) }}</span
                >
              </div>
            </div>
            <div class="freshness-item">
              <div class="freshness-label">Court Records</div>
              <div class="freshness-value">
                <span class="freshness-date">{{
                  formatDate(meta?.courts?.data_through)
                }}</span>
                <span class="freshness-updated"
                  >Updated
                  {{ formatRelativeTime(meta?.courts?.last_updated) }}</span
                >
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Methodology -->
      <section class="content-section">
        <div class="section-header">
          <div class="section-icon">
            <v-icon icon="mdi-clipboard-text-outline" size="24" />
          </div>
          <h2 class="section-title">Methodology & Limitations</h2>
        </div>
        <div class="section-content">
          <div class="methodology-grid">
            <div class="method-item">
              <h3>Data Updates</h3>
              <p>
                Shooting victim data is updated daily via automated ETL
                pipelines. The Philadelphia Police Department's Statistics Unit
                manually enters data from detective reports, with updates
                typically available by 10:30 AM on weekdays.
              </p>
            </div>
            <div class="method-item">
              <h3>Officer-Involved Shootings</h3>
              <p>
                This dashboard only includes data for criminal shooting victims,
                excluding officer-involved shootings, due to differences in
                reporting fields between the datasets. For more information, see
                the
                <a
                  href="https://www.phillypolice.com/ois"
                  target="_blank"
                  rel="noopener noreferrer"
                  @click="
                    trackExternalLink(
                      'Officer-Involved Shootings',
                      'https://www.phillypolice.com/ois'
                    )
                  "
                  >PPD's website</a
                >
                on officer-involed shootings.
              </p>
            </div>
            <div class="method-item">
              <h3>Court Case Linkage</h3>
              <p>
                Public court records are updated weekly by searching for each
                incident's police DC number in the Pennsylvania Unified Judicial
                System's public portal using automated web scraping.
              </p>
            </div>
            <div class="method-item">
              <h3>Homicide Counts</h3>
              <p>
                The total homicide count from PPD includes all homicides, not
                just firearm-related deaths. Fatal shootings in this dataset may
                undercount total gun homicides.
              </p>
            </div>
            <div class="method-item">
              <h3>Data Accuracy</h3>
              <p>
                All data is preliminary and may differ from other official
                sources. This tool is for informational purposes and should not
                be used as the sole source for research or policy decisions.
              </p>
            </div>
          </div>
        </div>
      </section>

      <!-- Open Source -->
      <section class="content-section">
        <div class="section-header">
          <div class="section-icon">
            <v-icon icon="mdi-github" size="24" />
          </div>
          <h2 class="section-title">Open Source</h2>
        </div>
        <div class="section-content">
          <p>
            This project is fully open source. Built with Vue 3, TypeScript, and
            MapLibre GL on the frontend, with a FastAPI backend and automated
            Python ETL pipelines, the complete codebase is available for anyone
            to explore, learn from, or contribute to.
          </p>
          <a
            href="https://github.com/nickhand/philly-gun-violence-dashboard"
            target="_blank"
            rel="noopener noreferrer"
            class="github-button"
            @click="
              trackExternalLink(
                'GitHub Repository',
                'https://github.com/nickhand/philly-gun-violence-dashboard'
              )
            "
          >
            <v-icon icon="mdi-github" size="20" />
            <span>View on GitHub</span>
            <v-icon icon="mdi-arrow-right" size="18" />
          </a>
        </div>
      </section>

      <!-- Contact -->
      <section class="content-section contact-section">
        <div class="section-header section-header-centered">
          <div class="section-icon">
            <v-icon icon="mdi-email-outline" size="24" />
          </div>
          <h2 class="section-title">Get in Touch</h2>
        </div>
        <div class="section-content">
          <p>Found a bug? Have a suggestion? Interested in working together?</p>
          <div class="contact-links">
            <a
              href="mailto:nicholas.adam.hand@gmail.com"
              class="contact-button"
              @click="
                trackExternalLink(
                  'Email',
                  'mailto:nicholas.adam.hand@gmail.com'
                )
              "
            >
              <v-icon icon="mdi-email" size="20" />
              <span>nicholas.adam.hand@gmail.com</span>
            </a>
            <a
              href="https://nickhand.dev"
              target="_blank"
              rel="noopener noreferrer"
              class="contact-button"
              @click="trackExternalLink('Website', 'https://nickhand.dev')"
            >
              <v-icon icon="mdi-web" size="20" />
              <span>nickhand.dev</span>
            </a>
          </div>
        </div>
      </section>
    </main>

    <!-- Footer -->
    <app-footer />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
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
        "Learn about the Philadelphia Gun Violence Dashboard - an open-source project visualizing shooting incidents with daily-updated public data. Built with Vue 3, FastAPI, and MapLibre.",
    },
  ],
  link: [
    {
      rel: "canonical",
      href: "https://nickhand.dev/philly-gun-violence-map/about",
    },
  ],
});
</script>

<style scoped>
.about-page-wrapper {
  background-color: #2a3136;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
}

.about-page {
  flex: 1;
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
  padding: 0 24px 40px;
}

/* Hero Section */
.hero-section {
  text-align: center;
  padding: 100px 0 60px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  margin-bottom: 48px;
}

.hero-title {
  font-family: var(--heading-font-family);
  font-size: 2.5rem;
  font-weight: 700;
  color: #ffffff;
  margin-bottom: 16px;
  letter-spacing: -0.02em;
}

.hero-subtitle {
  font-size: 1.2rem;
  color: rgba(255, 255, 255, 0.7);
  max-width: 600px;
  margin: 0 auto;
  line-height: 1.6;
}

/* Content Sections */
.content-section {
  margin-bottom: 56px;
  position: relative;
}

/* Section Header - icon and title inline */
.section-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.section-header-centered {
  justify-content: center;
}

.section-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  background: linear-gradient(135deg, #4a7080 0%, #5a7a8f 100%);
  border-radius: 10px;
  color: white;
  flex-shrink: 0;
}

.section-title {
  font-family: var(--heading-font-family);
  font-size: 1.5rem;
  font-weight: 600;
  color: #ffffff;
  letter-spacing: -0.01em;
  margin: 0;
}

.section-content {
  color: rgba(255, 255, 255, 0.85);
  line-height: 1.7;
}

.section-content p {
  margin-bottom: 16px;
}

.section-content p:last-child {
  margin-bottom: 0;
}

/* Text Links */
.text-link {
  color: #7ab5e5;
  text-decoration: none;
  font-weight: 500;
  transition: color 0.2s;
}

.text-link:hover {
  color: #9ecbf0;
  text-decoration: underline;
}

/* Feature List */
.feature-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 12px;
}

.feature-list li {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.list-icon {
  color: #5a9a6e;
  flex-shrink: 0;
  margin-top: 2px;
}

/* Data Sources */
.data-sources {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 20px;
  margin-top: 20px;
}

.data-source-card {
  display: block;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 24px;
  text-decoration: none;
  transition: all 0.2s ease;
}

.data-source-card:hover {
  background: rgba(74, 112, 128, 0.25);
  border-color: rgba(122, 181, 229, 0.4);
  transform: translateY(-2px);
}

.source-header {
  color: #ffffff;
  font-weight: 600;
  font-size: 1.05rem;
  margin-bottom: 12px;
}

.data-source-card p {
  color: rgba(255, 255, 255, 0.7);
  font-size: 0.9rem;
  line-height: 1.5;
  margin-bottom: 12px;
}

.source-origin {
  display: inline-block;
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.5);
  background: rgba(255, 255, 255, 0.05);
  padding: 4px 10px;
  border-radius: 4px;
  transition: all 0.2s ease;
}

.data-source-card:hover .source-origin {
  background: rgba(122, 181, 229, 0.2);
  color: #7ab5e5;
}

.source-origin:hover {
  background: rgba(122, 181, 229, 0.4) !important;
  color: #ffffff !important;
}

/* Data Freshness */
.freshness-loading,
.freshness-error {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.9rem;
}

.freshness-error {
  color: rgba(255, 150, 150, 0.8);
}

.freshness-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.freshness-item {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  padding: 16px 20px;
}

.freshness-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.6);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin-bottom: 8px;
}

.freshness-value {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.freshness-date {
  font-size: 1.1rem;
  font-weight: 500;
  color: #7ab5e5;
}

.freshness-updated {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.5);
}

/* Methodology Grid */
.methodology-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 24px;
  margin-top: 8px;
}

.method-item {
  padding: 20px;
  background: rgba(255, 255, 255, 0.02);
  border-left: 3px solid #5a7a8f;
  border-radius: 0 8px 8px 0;
}

.method-item h3 {
  font-family: var(--heading-font-family);
  font-size: 1rem;
  font-weight: 600;
  color: #ffffff;
  margin-bottom: 8px;
}

.method-item p {
  color: rgba(255, 255, 255, 0.7);
  font-size: 0.9rem;
  line-height: 1.6;
  margin: 0;
}

/* GitHub Button */
.github-button {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: linear-gradient(135deg, #4a7080 0%, #5a7a8f 100%);
  color: white;
  padding: 14px 24px;
  border-radius: 8px;
  text-decoration: none;
  font-weight: 400;
  font-size: 0.95rem;
  margin-top: 16px;
  transition: all 0.2s ease;
}

.github-button:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 20px rgba(74, 112, 128, 0.4);
}

/* Contact Section */
.contact-section {
  text-align: center;
  padding: 48px 0 0;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  margin-top: 48px;
  margin-bottom: 0;
}

.contact-section .section-content p {
  font-size: 1.1rem;
  color: rgba(255, 255, 255, 0.7);
}

.contact-links {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 16px;
  margin-top: 24px;
}

.contact-button {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.9);
  padding: 12px 20px;
  border-radius: 8px;
  text-decoration: none;
  font-size: 0.95rem;
  transition: all 0.2s ease;
}

.contact-button:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(122, 181, 229, 0.3);
}

/* Footer */
.about-footer {
  text-align: center;
  padding-top: 48px;
}

/* Responsive */
@media (max-width: 768px) {
  .hero-section {
    padding: 80px 0 40px;
  }

  .hero-title {
    font-size: 1.8rem;
  }

  .hero-subtitle {
    font-size: 1rem;
  }

  .section-header {
    gap: 12px;
  }

  .section-icon {
    width: 38px;
    height: 38px;
  }

  .section-title {
    font-size: 1.3rem;
  }

  .tech-grid,
  .data-sources,
  .methodology-grid {
    grid-template-columns: 1fr;
  }

  .feature-list li {
    padding: 10px 12px;
  }

  .contact-links {
    flex-direction: column;
    align-items: center;
  }

  .contact-button {
    width: 100%;
    max-width: 300px;
    justify-content: center;
  }
}

@media (max-width: 480px) {
  .about-page {
    padding: 0 16px 40px;
  }

  .hero-title {
    font-size: 1.5rem;
  }

  .github-button {
    width: 100%;
    justify-content: center;
  }
}
</style>
