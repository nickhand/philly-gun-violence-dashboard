<template>
  <section class="dashboard-view">
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

    <!-- Map dashboard with filters -->
    <div v-if="currentData !== null">
      <mapping-dashboard />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useShootingsStore } from "@/shared/stores/shootings";
import DashboardNavbar from "@/features/dashboard/components/DashboardNavbar.vue";
import HeaderMessage from "@/features/dashboard/components/HeaderMessage.vue";
import MappingDashboard from "@/features/map/components/MappingDashboard.vue";

// Access shootings store.
const shootingsStore = useShootingsStore();
const { dataYears, selectedYear, currentData, isLoadingData } =
  storeToRefs(shootingsStore);

// Local selected year state for the dropdown.
const selectedYearLocal = ref<number | null | undefined>(selectedYear.value);

// Derived state for header message.
const showOverlay = computed(() => isLoadingData.value);
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
  // Fetch data when year changes
  await shootingsStore.fetchShootingsData(next);
});

function handleSelectedYearChange(next: number | null) {
  selectedYearLocal.value = next;
}
</script>

<style scoped>
.dashboard-view {
  background-color: #353d42;
  min-height: 100vh;
}
</style>
