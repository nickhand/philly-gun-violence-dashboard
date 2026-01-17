<template>
  <div class="app-navbar">
    <!-- Overlay when data is loading -->
    <v-overlay
      :model-value="showOverlay"
      :opacity="OVERLAY_OPACITY"
      :scrim="OVERLAY_COLOR"
    />

    <!-- Back button (for About page) -->
    <v-btn
      v-if="showBackButton"
      class="nav-button"
      variant="outlined"
      density="compact"
      color="white"
      height="38"
      :ripple="false"
      @click="handleBackClick"
    >
      <v-icon start icon="mdi-arrow-left" />
      <span>Back</span>
    </v-btn>

    <!-- Info button (for Dashboard page) -->
    <v-btn
      v-else
      class="nav-button"
      variant="outlined"
      density="compact"
      color="white"
      height="38"
      :ripple="false"
      title="About page"
      @click="handleInfoClick"
    >
      <v-icon start icon="mdi-information-outline" />
      <span>Info</span>
    </v-btn>

    <!-- Year selector (only on Dashboard) -->
    <div class="year-message" v-if="showYearSelector">
      <div class="year-message__label">Viewing data for</div>
      <v-select
        class="year-select"
        v-model="value"
        :items="yearOptions"
        variant="underlined"
        density="compact"
        hide-details
        color="white"
        base-color="white"
        bg-color="transparent"
        no-auto-scroll
        :ripple="false"
        :style="{ '--select-font-size': '1.2rem' }"
        @update:model-value="handleYearChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { track } from "@/shared/analytics";
import { OVERLAY_OPACITY, OVERLAY_COLOR } from "@/shared/config/overlay";

const props = withDefaults(
  defineProps<{
    /**
     * Available years for filtering data.
     */
    dataYears?: number[];
    /**
     * Currently selected year for filtering data.
     */
    selectedYear?: number | null;
    /**
     * Whether to show the loading overlay.
     */
    showOverlay?: boolean;
    /**
     * Whether to show the year selector dropdown.
     */
    showYearSelector?: boolean;
    /**
     * Whether to show the back button instead of info button.
     */
    showBackButton?: boolean;
  }>(),
  {
    dataYears: () => [],
    selectedYear: null,
    showOverlay: false,
    showYearSelector: false,
    showBackButton: false,
  }
);

// Emit event to update selected year in the parent component.
const emit = defineEmits<{
  (e: "update:selectedYear", value: number | null): void;
}>();

// Access Vue Router for navigation.
const router = useRouter();

// Compute year options for the dropdown.
const yearOptions = computed(() => [
  "All Years",
  ...props.dataYears.map((year) => String(year)),
]);

// Local state for the dropdown value.
const value = ref<string | null>(null);

/**
 * Watch for changes in the selectedYear prop to update the dropdown value.
 */
watch(
  () => props.selectedYear,
  (newYear) => {
    // Keep the dropdown value in sync with the store.
    value.value =
      newYear === null || newYear === undefined ? "All Years" : String(newYear);
  },
  { immediate: true }
);

/**
 * Handle year selection changes from the dropdown.
 */
function handleYearChange(nextValue: string | null) {
  if (!nextValue) return;

  // Track year change analytics
  const previousYear = value.value;
  track("year_changed", {
    year: nextValue,
    previous_year: previousYear,
  });

  // Emit normalized year values for the store.
  if (nextValue === "All Years") {
    emit("update:selectedYear", null);
  } else {
    emit("update:selectedYear", Number(nextValue));
  }
}

/**
 * Navigate to the About page when the Info button is clicked.
 */
function handleInfoClick() {
  router.replace("/about");
}

/**
 * Navigate back to the Dashboard when the Back button is clicked.
 */
function handleBackClick() {
  router.replace({
    path: "/",
    query: { year: props.selectedYear ?? undefined },
  });
}
</script>

<style scoped>
.app-navbar {
  width: 100%;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: flex-end;
  gap: 6px;
  padding: 10px 10px 10px 0;
  font-size: 1.2rem;
  color: rgb(var(--v-theme-secondary));
  background-color: rgb(var(--v-theme-background));
}

.nav-button {
  min-width: 100px;
  font-size: 1rem;
  text-transform: none;
  box-shadow: none;
}

.nav-button:hover {
  background-color: rgb(var(--v-theme-background));
  border-color: rgb(var(--v-theme-primary));
}

.year-message {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: rgb(var(--v-theme-primary));
}

.year-message__label {
  margin-top: 4px;
}

.year-select {
  width: fit-content;
  min-width: 80px;
  margin-top: 2px;
}

.year-select :deep(.v-field__input) {
  font-size: var(--select-font-size, 1rem);
  padding-top: 0;
  padding-bottom: 2px;
}

.year-select :deep(.v-field__outline) {
  --v-field-border-opacity: 1;
}
</style>
