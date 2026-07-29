<template>
  <section class="dashboard-view">
    <!-- Loading overlay (simple div, not v-overlay which teleports) -->
    <div
      v-if="showLoading"
      class="loading-overlay"
      role="status"
      aria-live="polite"
      aria-label="Loading dashboard data"
    >
      <span class="sr-only">Loading dashboard data</span>
    </div>

    <!-- Skip Links for Keyboard Navigation -->
    <nav class="skip-links" aria-label="Skip navigation">
      <a href="#main-content" class="skip-link">Skip to main content</a>
      <a href="#filters" class="skip-link">Skip to filters</a>
      <a href="#charts" class="skip-link">Skip to charts</a>
    </nav>

    <app-navbar
      :data-years="dataYears"
      :selected-year="selectedYear"
      :show-year-selector="true"
      @update:selected-year="handleSelectedYearChange"
    />

    <!-- Map dashboard with filters, header, and charts -->
    <main id="main-content" tabindex="-1">
      <mapping-dashboard />
    </main>

    <!-- Error modal -->
    <v-dialog
      v-model="showErrorDialog"
      max-width="500"
      persistent
      aria-labelledby="error-dialog-title"
      aria-describedby="error-dialog-description"
    >
      <v-card class="error-modal">
        <v-card-title id="error-dialog-title" class="error-title">
          <v-icon icon="mdi-alert-circle-outline" class="mr-2" aria-hidden="true" />
          Unable to Load Data
        </v-card-title>
        <v-card-text id="error-dialog-description" class="error-body">
          {{ currentError || defaultErrorMessage }}
        </v-card-text>
        <v-card-actions class="error-actions">
          <router-link to="/about" class="about-link">
            Learn more about this project
          </router-link>
          <v-spacer />
          <v-btn variant="flat" color="primary" @click="retryLoad">
            <v-icon
              icon="mdi-refresh"
              class="mr-1"
              size="small"
              aria-hidden="true"
            />
            Retry
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Footer -->
    <app-footer
      :style="{ opacity: hasData ? 1 : 0, transition: 'opacity 0.3s ease-in' }"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { useHead } from "@unhead/vue";
import { useShootingsStore } from "@/shared/stores/shootings";
import { useLoadingState } from "@/pages/composables/useLoadingState";
import AppNavbar from "@/app/components/AppNavbar.vue";
import AppFooter from "@/app/components/AppFooter.vue";
import MappingDashboard from "@/pages/components/MappingDashboard.vue";

// SEO Meta Tags
useHead({
  title:
    "Philadelphia Gun Violence Dashboard | Interactive Shootings Map & Data",
  meta: [
    {
      name: "description",
      content:
        "Interactive map and charts visualizing gun violence and shooting incidents in Philadelphia. Explore daily-updated data by year, district, and neighborhood. Download in CSV and GeoJSON.",
    },
    {
      name: "keywords",
      content:
        "Philadelphia gun violence, Philly shootings, Philadelphia shootings map, gun violence dashboard, Philly crime map, Philadelphia crime data, shooting victims, download shootings data",
    },
  ],
  link: [
    {
      rel: "canonical",
      href: "https://nickhand.dev/philly-gun-violence-map/",
    },
  ],
});

// Access shootings store.
const shootingsStore = useShootingsStore();
const {
  sortedYears: dataYears,
  selectedYear,
  loadError,
  metaError,
  hasData,
} = storeToRefs(shootingsStore);

// Centralized loading state (navbar doesn't need mapReady check)
const { showLoading } = useLoadingState();

// Access route for URL query params
const route = useRoute();

// Error handling
const showErrorDialog = ref(false);
const defaultErrorMessage =
  "We couldn't load the shootings data right now. Please retry or try again later.";

/**
 * Current error message to display.
 */
const currentError = computed(
  () => loadError.value || (metaError.value ? defaultErrorMessage : null),
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
  { immediate: true },
);

onMounted(async () => {
  const startTime = import.meta.env.DEV ? performance.now() : 0;

  // Read year from URL BEFORE loading data (which sets default year)
  const urlYear = route.query.year;
  if (urlYear && typeof urlYear === "string") {
    if (urlYear === "All Years") {
      shootingsStore.setSelectedYear(null);
    } else {
      const parsedYear = parseInt(urlYear, 10);
      if (!isNaN(parsedYear)) {
        shootingsStore.setSelectedYear(parsedYear);
      }
    }
  }

  // Load dataset - this fetches meta + rows
  await shootingsStore.loadDatasetIfNeeded();

  if (import.meta.env.DEV) {
    console.log(
      `[DashboardPage] Loaded in ${(performance.now() - startTime).toFixed(1)}ms (year=${shootingsStore.selectedYear}, loaded=${[...shootingsStore.loadedYears].join(",")})`,
    );
  }
});

/**
 * Handle selected year change from navbar dropdown.
 */
function handleSelectedYearChange(next: number | null) {
  shootingsStore.setSelectedYear(next);
}

/**
 * Retry loading data after an error.
 */
async function retryLoad() {
  showErrorDialog.value = false;
  shootingsStore.$patch({
    loadError: null,
    metaError: false,
  });

  // Retry loading the dataset
  await shootingsStore.reloadDataset();
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

/* Loading overlay */
.loading-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(53, 61, 66, 0.9);
  z-index: 9999;
}
</style>
