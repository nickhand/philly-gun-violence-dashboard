<template>
  <section class="dashboard-view">
    <!-- Skip Links for Keyboard Navigation -->
    <nav class="skip-links" aria-label="Skip navigation">
      <a href="#main-content" class="skip-link">Skip to main content</a>
      <a href="#filters" class="skip-link">Skip to filters</a>
      <a href="#charts" class="skip-link">Skip to charts</a>
    </nav>

    <dashboard-navbar
      :data-years="dataYears"
      :selected-year="selectedYearLocal"
      :show-overlay="showOverlay"
      @update:selected-year="handleSelectedYearChange"
    />
    <header-message
      :fatal="fatalCount"
      :nonfatal="nonfatalCount"
      :current-year="currentYear"
      :min-year="minYear"
      :selected-year="selectedYearLocal"
      :latest-data-date="latestDataDate"
      :show-overlay="showOverlay"
    />

    <!-- Screen reader announcement for filter changes -->
    <div aria-live="polite" aria-atomic="true" class="sr-only" role="status">
      {{ filterAnnouncement }}
    </div>

    <!-- Map dashboard with filters -->
    <main id="main-content" v-if="currentData !== null">
      <mapping-dashboard
        @map-ready="handleMapReady"
        @filtered-features="handleFilteredFeatures"
      />
    </main>

    <!-- Chart dashboard showing breakdowns by category -->
    <chart-dashboard id="charts" :features="filteredFeatures" />

    <!-- Footer -->
    <footer class="dashboard-footer">
      <p>
        Built with 💙 in Philadelphia by
        <a
          href="https://nickhand.dev"
          target="_blank"
          rel="noopener noreferrer"
          class="footer-link"
        >
          Nick Hand
        </a>
        • {{ new Date().getFullYear() }}
      </p>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { useHead } from "@unhead/vue";
import { useShootingsStore } from "@/shared/stores/shootings";
import DashboardNavbar from "@/features/dashboard/components/DashboardNavbar.vue";
import HeaderMessage from "@/features/dashboard/components/HeaderMessage.vue";
import MappingDashboard from "@/features/map/components/MappingDashboard.vue";
import ChartDashboard from "@/features/charts/components/ChartDashboard.vue";

// SEO Meta Tags
useHead({
  title: "Philadelphia Gun Violence Dashboard | Interactive Shootings Map",
  meta: [
    {
      name: "description",
      content:
        "Interactive map and charts visualizing gun violence and shooting incidents in Philadelphia. Explore daily-updated data by year, district, and neighborhood.",
    },
    {
      name: "keywords",
      content:
        "Philadelphia gun violence, Philly shootings, Philadelphia shootings map, gun violence dashboard, Philly crime map, Philadelphia crime data, shooting victims",
    },
  ],
  link: [
    {
      rel: "canonical",
      href: "https://nickhand.dev/philly-gun-violence-map/",
    },
  ],
});

// Types
interface Feature {
  properties: Record<string, unknown>;
}

// Access shootings store.
const shootingsStore = useShootingsStore();
const {
  dataYears,
  selectedYear,
  currentData,
  isLoadingData,
  isFetchingYears,
  overlayHold,
  dataLoadError,
  dataYearsError,
} = storeToRefs(shootingsStore);

// Access route for URL query params
const route = useRoute();

// Local selected year state for the dropdown.
const selectedYearLocal = ref<number | null | undefined>(selectedYear.value);

// Track whether the map component is ready (initialized and sources loaded)
const mapReady = ref(false);

// Filtered features from MappingDashboard for chart dashboard
const filteredFeatures = ref<Feature[]>([]);

// Previous count for announcement comparison
const previousCount = ref<number | null>(null);

/**
 * Announcement text for screen readers when filters change.
 * Uses aria-live region to announce without interrupting.
 */
const filterAnnouncement = computed(() => {
  const count = filteredFeatures.value.length;
  if (previousCount.value !== null && previousCount.value !== count) {
    return `Showing ${count.toLocaleString()} shooting victim${
      count !== 1 ? "s" : ""
    }`;
  }
  return "";
});

/**
 * Whether to show the loading overlay.
 * Matches Vue 2 behavior: show overlay if fetching years, loading data,
 * overlay hold is set, there's an error, or the map is still initializing.
 */
const showOverlay = computed(
  () =>
    isFetchingYears.value ||
    isLoadingData.value ||
    overlayHold.value ||
    !!dataLoadError.value ||
    dataYearsError.value ||
    (currentData.value !== null && !mapReady.value)
);
const currentYear = computed(() => new Date().getFullYear());
const minYear = computed(
  () => dataYears.value[dataYears.value.length - 1] ?? currentYear.value
);
const latestDataDate = computed(() => null as Date | null);

/**
 * Count fatal shooting victims for the selected year.
 */
const fatalCount = computed(() => {
  if (!currentData.value) return 0;
  return currentData.value.features.filter((f) => f.properties.fatal).length;
});

/**
 * Count nonfatal shooting victims for the selected year.
 */
const nonfatalCount = computed(() => {
  if (!currentData.value) return 0;
  return currentData.value.features.filter((f) => !f.properties.fatal).length;
});

onMounted(async () => {
  // Read year from URL BEFORE fetching data years (which sets default year)
  const urlYear = route.query.year;
  if (urlYear && typeof urlYear === "string") {
    if (urlYear === "All Years") {
      // "All Years" means null
      shootingsStore.setSelectedYear(null);
      selectedYearLocal.value = null;
    } else {
      const parsedYear = parseInt(urlYear, 10);
      if (!isNaN(parsedYear)) {
        // Set year in store before fetchDataYears to prevent default override
        shootingsStore.setSelectedYear(parsedYear);
        selectedYearLocal.value = parsedYear;
      }
    }
  }

  await shootingsStore.fetchDataYears();
  // Fetch initial data for the selected year
  if (selectedYear.value !== undefined) {
    await shootingsStore.fetchShootingsData(selectedYear.value);
  }
});

watch(selectedYear, (next) => {
  selectedYearLocal.value = next;
});

watch(selectedYearLocal, async (next) => {
  shootingsStore.setSelectedYear(next);
  await shootingsStore.fetchShootingsData(next);
});

/**
 * Handle selected year change from navbar dropdown.
 */
function handleSelectedYearChange(next: number | null) {
  selectedYearLocal.value = next;
}

/**
 * Handle map ready event from MappingDashboard.
 * Sets mapReady to true so overlay can hide.
 */
function handleMapReady() {
  mapReady.value = true;
}

/**
 * Handle filtered features update from MappingDashboard.
 * Stores features for chart dashboard to visualize.
 */
function handleFilteredFeatures(features: Feature[]) {
  previousCount.value = filteredFeatures.value.length;
  filteredFeatures.value = features;
}
</script>

<style scoped>
.dashboard-view {
  background-color: #353d42;
  min-height: 100vh;
}

/* Skip links - visible only on focus for keyboard users */
.skip-links {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 9999;
  display: flex;
  gap: 4px;
}

.skip-link {
  position: absolute;
  left: -9999px;
  top: auto;
  width: 1px;
  height: 1px;
  overflow: hidden;
  padding: 0.75rem 1rem;
  background: #1e88e5;
  color: white;
  text-decoration: none;
  font-weight: 600;
  border-radius: 0 0 4px 0;
}

.skip-link:focus {
  position: static;
  width: auto;
  height: auto;
  overflow: visible;
  outline: 2px solid white;
  outline-offset: 2px;
}

/* Footer */
.dashboard-footer {
  text-align: center;
  padding-top: 48px;
  padding-bottom: 2rem;
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.9rem;
}

.dashboard-footer p {
  margin: 0;
}

.footer-link {
  color: rgba(255, 255, 255, 0.6);
  text-decoration: none;
  transition: color 0.2s ease;
}

.footer-link:hover {
  color: #7ab5e5;
  text-decoration: underline;
}
</style>
