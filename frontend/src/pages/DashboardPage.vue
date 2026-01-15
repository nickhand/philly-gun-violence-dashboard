<template>
  <section class="dashboard-view">
    <!-- Skip Links for Keyboard Navigation -->
    <nav class="skip-links" aria-label="Skip navigation">
      <a href="#main-content" class="skip-link">Skip to main content</a>
      <a href="#filters" class="skip-link">Skip to filters</a>
      <a href="#charts" class="skip-link">Skip to charts</a>
    </nav>

    <app-navbar
      :data-years="dataYears"
      :selected-year="selectedYearLocal"
      :show-overlay="showOverlay"
      :show-year-selector="true"
      @update:selected-year="handleSelectedYearChange"
    />
    <dashboard-header
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

    <!-- Error modal -->
    <v-dialog v-model="showErrorDialog" max-width="500" persistent>
      <v-card class="error-modal">
        <v-card-title class="error-title">
          <v-icon icon="mdi-alert-circle-outline" class="mr-2" />
          Unable to Load Data
        </v-card-title>
        <v-card-text class="error-body">
          {{ currentError || defaultErrorMessage }}
        </v-card-text>
        <v-card-actions class="error-actions">
          <router-link to="/about" class="about-link">
            Learn more about this project
          </router-link>
          <v-spacer />
          <v-btn variant="flat" color="primary" @click="retryLoad">
            <v-icon icon="mdi-refresh" class="mr-1" size="small" />
            Retry
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Footer -->
    <app-footer />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { useHead } from "@unhead/vue";
import { useShootingsStore } from "@/shared/stores/shootings";
import AppNavbar from "@/app/components/AppNavbar.vue";
import AppFooter from "@/app/components/AppFooter.vue";
import DashboardHeader from "@/pages/components/DashboardHeader.vue";
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
  properties: Record<string, unknown> | null;
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

// Error handling
const showErrorDialog = ref(false);
const defaultErrorMessage =
  "We couldn't load the shootings data right now. Please retry or try again later.";

/**
 * Current error message to display.
 */
const currentError = computed(
  () =>
    dataLoadError.value || (dataYearsError.value ? defaultErrorMessage : null)
);

/**
 * Watch for errors and show the dialog.
 * Use immediate: true so dialog shows if error exists on mount (e.g., navigating back).
 */
watch(
  currentError,
  (error) => {
    showErrorDialog.value = !!error;
  },
  { immediate: true }
);

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

/**
 * Retry loading data after an error.
 */
async function retryLoad() {
  showErrorDialog.value = false;
  shootingsStore.$patch({
    dataLoadError: null,
    dataYearsError: false,
  });

  // Retry fetching data years first
  const years = await shootingsStore.fetchDataYears();

  // If years were fetched successfully and we have a selected year, fetch that data
  if (years && years.length > 0 && selectedYear.value !== undefined) {
    await shootingsStore.fetchShootingsData(selectedYear.value);
  }
}
</script>

<style scoped>
.dashboard-view {
  background-color: rgb(var(--v-theme-background));
  min-height: 100dvh;
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
}

/* Error Modal */
.error-modal {
  background-color: rgb(var(--v-theme-surface));
}

.error-title {
  font-family: var(--heading-font-family);
  font-size: 1.25rem;
  font-weight: 600;
  color: rgba(var(--v-theme-on-surface), 0.95);
  display: flex;
  align-items: center;
}

.error-title :deep(.v-icon) {
  color: #ff6b6b;
}

.error-body {
  color: rgba(var(--v-theme-on-surface), 0.87);
  font-size: 1rem;
  line-height: 1.5;
  padding: 16px 24px;
}

.error-actions {
  padding: 8px 16px 16px;
  align-items: center;
}

.about-link {
  font-size: 0.875rem;
  color: rgba(var(--v-theme-on-surface), 0.7);
  text-decoration: none;
  transition: color 0.2s ease;
}

.about-link:hover {
  color: rgb(var(--v-theme-primary));
  text-decoration: underline;
}
</style>
