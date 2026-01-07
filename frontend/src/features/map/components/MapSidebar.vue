<template>
  <div class="map-sidebar">
    <!-- Header -->
    <div class="sidebar-header">
      <div class="d-flex align-center pa-4">
        <v-icon icon="mdi-filter-variant" class="mr-2" />
        <span class="text-h6">Filters</span>
      </div>

      <v-divider />

      <!-- Statistics Summary -->
      <div class="pa-4">
        <div class="stats-summary">
          <div class="stat-item">
            <span class="stat-label">Showing:</span>
            <span class="stat-value">{{ featureCount.toLocaleString() }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Total:</span>
            <span class="stat-value">{{ totalCount.toLocaleString() }}</span>
          </div>
          <div v-if="filterPercentage < 100" class="stat-item">
            <span class="stat-label">Filtered:</span>
            <span class="stat-value">{{ filterPercentage.toFixed(1) }}%</span>
          </div>
        </div>
      </div>

      <v-divider />

      <!-- Action Buttons -->
      <div class="pa-4">
        <v-btn
          variant="outlined"
          color="secondary"
          block
          @click="handleResetAll"
        >
          <v-icon icon="mdi-refresh" class="mr-2" />
          Reset All
        </v-btn>
      </div>

      <v-divider />

      <!-- Download Section -->
      <div class="pa-4">
        <label class="filter-label mb-2">Export Data</label>
        <v-btn-group variant="outlined" divided density="compact" class="w-100">
          <v-btn @click="handleDownload('geojson')">
            <v-icon icon="mdi-map" class="mr-1" size="small" />
            GeoJSON
          </v-btn>
          <v-btn @click="handleDownload('csv')">
            <v-icon icon="mdi-table" class="mr-1" size="small" />
            CSV
          </v-btn>
          <v-btn @click="handleDownload('json')">
            <v-icon icon="mdi-code-json" class="mr-1" size="small" />
            JSON
          </v-btn>
        </v-btn-group>
      </div>
    </div>

    <!-- Scrollable Filter Controls -->
    <div class="sidebar-inner-content">
      <div class="pa-4 filter-controls">
        <div
          v-for="filter in filters"
          :key="filter.id"
          class="filter-group mb-4"
        >
          <!-- Range Filter (Slider) -->
          <div v-if="filter.type === 'range'" class="filter-item">
            <label class="filter-label">{{ filter.label }}</label>
            <v-range-slider
              :model-value="getFilterValue(filter.id, [filter.min, filter.max])"
              :min="filter.min"
              :max="filter.max"
              :step="filter.step || 1"
              thumb-label="always"
              class="mt-2"
              @update:model-value="handleRangeChange(filter.id, $event)"
            />
          </div>

          <!-- Checkbox Filter -->
          <div v-else-if="filter.type === 'checkbox'" class="filter-item">
            <v-checkbox
              :model-value="getFilterValue(filter.id, filter.defaultValue)"
              :label="filter.label"
              @update:model-value="handleCheckboxChange(filter.id, $event)"
            />
          </div>

          <!-- Select Filter (Dropdown) -->
          <div v-else-if="filter.type === 'select'" class="filter-item">
            <label class="filter-label">{{ filter.label }}</label>
            <v-select
              :model-value="getFilterValue(filter.id, null)"
              :items="filter.options"
              item-title="label"
              item-value="value"
              clearable
              @update:model-value="handleSelectChange(filter.id, $event)"
            />
          </div>

          <!-- Multiselect Filter (Chips) -->
          <div v-else-if="filter.type === 'multiselect'" class="filter-item">
            <label class="filter-label">{{ filter.label }}</label>
            <v-select
              :model-value="getFilterValue(filter.id, [])"
              :items="filter.options"
              item-title="label"
              item-value="value"
              multiple
              chips
              closable-chips
              @update:model-value="handleMultiselectChange(filter.id, $event)"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * MapSidebar Component
 *
 * Sidebar with filter controls, statistics, and data export.
 * Displays filter UI based on FilterConfig type and emits filter changes.
 *
 * Filter Types Supported:
 * - range: Two-handle slider for numeric ranges (e.g., year, age)
 * - checkbox: Boolean filter (e.g., fatal/non-fatal)
 * - select: Single-select dropdown
 * - multiselect: Multi-select with chips (e.g., time of day, district)
 *
 * @component
 */

import { computed } from "vue";
import type { FilterConfig } from "../types";

// Props
interface Props {
  /** Filter configurations to render */
  filters: FilterConfig[];
  /** Active filter values keyed by filter ID */
  activeFilters: Map<string, any>;
  /** Number of features after filtering */
  featureCount: number;
  /** Total number of features (unfiltered) */
  totalCount: number;
}

const props = defineProps<Props>();

// Emits
const emit = defineEmits<{
  /** Emitted when a filter value changes */
  "filter-change": [dimensionId: string, value: any];
  /** Emitted when a single filter is reset */
  "filter-reset": [dimensionId: string];
  /** Emitted when reset all is clicked */
  "reset-all": [];
  /** Emitted when download button is clicked */
  download: [format: "geojson" | "csv" | "json"];
}>();

// Computed properties
/**
 * Percentage of features shown after filtering.
 * Used to display filter impact in statistics.
 */
const filterPercentage = computed(() => {
  if (props.totalCount === 0) return 100;
  return (props.featureCount / props.totalCount) * 100;
});

// Helper methods
/**
 * Get current filter value or default.
 * Retrieves value from activeFilters map or returns default.
 *
 * @param filterId - Filter dimension ID
 * @param defaultValue - Default value if no active filter
 * @returns Current filter value or default
 */
function getFilterValue(filterId: string, defaultValue: any): any {
  return props.activeFilters.get(filterId) ?? defaultValue;
}

// Event handlers
/**
 * Handle range slider change.
 * Emits filter-change with [min, max] tuple.
 *
 * @param filterId - Filter dimension ID
 * @param value - New range value [min, max]
 */
function handleRangeChange(filterId: string, value: [number, number]): void {
  emit("filter-change", filterId, value);
}

/**
 * Handle checkbox change.
 * Emits filter-change with boolean value.
 * Clears filter if unchecked (null value).
 *
 * @param filterId - Filter dimension ID
 * @param value - New checkbox value
 */
function handleCheckboxChange(filterId: string, value: boolean): void {
  // Emit null if unchecked to clear filter
  emit("filter-change", filterId, value === false ? null : value);
}

/**
 * Handle select dropdown change.
 * Emits filter-change with selected value.
 *
 * @param filterId - Filter dimension ID
 * @param value - Selected value
 */
function handleSelectChange(filterId: string, value: any): void {
  emit("filter-change", filterId, value);
}

/**
 * Handle multiselect change.
 * Emits filter-change with array of selected values.
 *
 * @param filterId - Filter dimension ID
 * @param value - Array of selected values
 */
function handleMultiselectChange(filterId: string, value: any[]): void {
  emit("filter-change", filterId, value);
}

/**
 * Handle reset all filters.
 * Emits reset-all event to parent.
 */
function handleResetAll(): void {
  emit("reset-all");
}

/**
 * Handle data download.
 * Emits download event with selected format.
 *
 * @param format - Export format (geojson, csv, json)
 */
function handleDownload(format: "geojson" | "csv" | "json"): void {
  emit("download", format);
}
</script>

<style scoped>
.map-sidebar {
  width: 30%;
  min-width: 300px;
  height: 800px;
  display: flex;
  flex-direction: column;
  border-left: 5px solid #868b8e;
  background-color: #353d42;
  position: relative;
}

@media only screen and (max-width: 767px) {
  .map-sidebar {
    width: 100%;
    height: 800px;
    border-top: 5px solid #868b8e;
    border-left-width: 0px;
  }
}

.sidebar-header {
  text-align: center;
  padding: 5px;
  background-color: #353d42;
}

.sidebar-inner-content {
  background-color: #353d42;
  overflow-y: scroll;
  flex: 1;
}

.stats-summary {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stat-item {
  display: flex;
  justify-content: space-between;
}

.stat-label {
  color: rgba(255, 255, 255, 0.7);
  font-size: 0.875rem;
}

.stat-value {
  font-weight: 500;
  color: #fff;
}

.filter-label {
  display: block;
  margin-bottom: 8px;
  font-weight: 500;
  font-size: 0.875rem;
}

.filter-item {
  margin-bottom: 16px;
}

/* Vuetify component overrides */
:deep(.v-btn-group) {
  width: 100%;
}

:deep(.v-btn-group .v-btn) {
  flex: 1;
}
</style>
