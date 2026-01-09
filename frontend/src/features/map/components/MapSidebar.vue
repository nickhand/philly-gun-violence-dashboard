<template>
  <div class="map-sidebar">
    <!-- Loading overlay -->
    <v-overlay
      :model-value="showOverlay"
      contained
      persistent
      class="sidebar-overlay"
    >
      <v-progress-circular indeterminate color="primary" />
    </v-overlay>

    <!-- Sidebar Header -->
    <div class="sidebar-header">
      <div class="data-size-section">
        <div class="data-size-message mt-3">
          Showing locations for
          <span class="highlight-count">{{ formatNumber(pointsOnMap) }}</span>
          {{ markerTitle }}<span v-if="pointsOnMap !== 1">s</span>
        </div>
        <div v-if="missingPoints > 0" class="sidebar-note">
          Note: {{ missingPoints }} {{ markerShortTitle
          }}<span v-if="missingPoints > 1">s</span>
          not shown due to missing locations
        </div>
      </div>

      <div class="buttons-section">
        <v-btn
          class="action-button"
          variant="outlined"
          color="white"
          block
          @click="$emit('download', 'geojson')"
        >
          <v-icon icon="mdi-download" class="mr-2" />
          Download Data
        </v-btn>

        <v-btn
          class="action-button mt-3"
          variant="outlined"
          color="white"
          block
          :disabled="!filterHelpers.hasAnyActiveFilters()"
          @click="$emit('reset-all')"
        >
          <v-icon icon="mdi-refresh" class="mr-2" />
          Reset All Filters
        </v-btn>
      </div>
    </div>

    <!-- Scrollable content -->
    <div class="sidebar-inner-content">
      <!-- Map Layers Section -->
      <v-container
        v-if="toggleableLayerNames.length > 0"
        class="sidebar-section"
      >
        <MapLayersPanel
          ref="layersPanelRef"
          :toggleable-layer-names="toggleableLayerNames"
          :overlay-layer-names="overlayLayerNames"
          :default-toggled-layer-names="defaultToggledLayerNames"
          @layer-change="
            (name, visible) => $emit('layer-change', name, visible)
          "
          @overlay-change="(name) => $emit('overlay-change', name)"
          @opacity-change="
            (name, opacity) => $emit('opacity-change', name, opacity)
          "
        />
      </v-container>

      <!-- Filters Section -->
      <v-container class="sidebar-section">
        <div class="section-title">Filters</div>
        <v-divider class="section-divider" />

        <v-expansion-panels
          v-model="expandedPanels"
          multiple
          variant="accordion"
          flat
        >
          <!-- Switch Filters -->
          <SwitchFilter
            v-for="filter in switchFilters"
            :key="filter.name"
            :model-value="filterHelpers.getFilterValue(filter.name) ?? false"
            :label="filter.label"
            @update:model-value="$emit('filter-change', filter.name, $event)"
          />

          <!-- Checkbox Filters -->
          <CheckboxFilter
            v-for="filter in checkboxFilters"
            :key="filter.name"
            :label="filter.label"
            :categories="filter.categories ?? []"
            :selected-values="filterHelpers.getCheckboxValues(filter.name)"
            :default-values="(filter.default as any[]) ?? []"
            :ncol="filter.ncol"
            @change="
              (value, checked) =>
                handleCheckboxChange(filter.name, value, checked)
            "
            @only="(value) => $emit('filter-change', filter.name, [value])"
            @reset="$emit('filter-reset', filter.name)"
          />

          <!-- Slider Filters -->
          <SliderFilter
            v-for="filter in sliderFilters"
            :key="filter.name"
            :label="filter.label"
            :model-value="filterHelpers.getSliderValue(filter)"
            :default-value="(filter.default as [number, number]) ?? [0, 100]"
            :min="filterHelpers.getSliderMin(filter)"
            :max="filterHelpers.getSliderMax(filter)"
            :step="1"
            :show-exclude-missing="filter.excludeMissing ?? false"
            :exclude-missing="excludeMissingValues[filter.name] ?? false"
            @update:model-value="$emit('filter-change', filter.name, $event)"
            @update:exclude-missing="
              handleExcludeMissingChange(filter.name, $event)
            "
            @reset="$emit('filter-reset', filter.name)"
          />
        </v-expansion-panels>
      </v-container>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * MapSidebar Component
 *
 * Sidebar with filter controls, layer toggles, and data export.
 *
 * Sections:
 * 1. Header: Data count, download button, reset all button
 * 2. Map Layers: Layer toggle checkboxes + aggregation dropdown
 * 3. Filters: Switch, checkbox, and slider filters
 *
 * @component
 */

import { ref, computed } from "vue";
import { format } from "d3-format";
import type { FilterConfig } from "../types";
import { useFilterHelpers } from "../composables/useFilterHelpers";
import { SwitchFilter, CheckboxFilter, SliderFilter } from "./filters";
import MapLayersPanel from "./MapLayersPanel.vue";

// Props
interface Props {
  filters: FilterConfig[];
  activeFilters: Map<string, any>;
  featureCount: number;
  totalCount: number;
  pointsOnMap?: number;
  toggleableLayerNames?: string[];
  overlayLayerNames?: string[];
  defaultToggledLayerNames?: string[];
  showOverlay?: boolean;
  markerTitle?: string;
  markerShortTitle?: string;
}

const props = withDefaults(defineProps<Props>(), {
  pointsOnMap: 0,
  toggleableLayerNames: () => [],
  overlayLayerNames: () => [],
  defaultToggledLayerNames: () => [],
  showOverlay: false,
  markerTitle: "shooting victim",
  markerShortTitle: "victim",
});

// Emits
const emit = defineEmits<{
  "filter-change": [dimensionId: string, value: any];
  "filter-reset": [dimensionId: string];
  "reset-all": [];
  download: [format: string];
  "layer-change": [layerName: string, visible: boolean];
  "overlay-change": [layerName: string | null];
  "opacity-change": [layerName: string, opacity: number];
}>();

// Composable for filter helpers
const filterHelpers = useFilterHelpers(
  () => props.filters,
  () => props.activeFilters
);

// Local state
const expandedPanels = ref<number[]>([]);
const excludeMissingValues = ref<Record<string, boolean>>({});
const layersPanelRef = ref<InstanceType<typeof MapLayersPanel> | null>(null);

// Initialize exclude missing values
props.filters.forEach((filter) => {
  if (filter.excludeMissing) {
    excludeMissingValues.value[filter.name] = false;
  }
});

// Computed
const formatNumber = (n: number) => format(",.0f")(n);
const missingPoints = computed(() => props.featureCount - props.pointsOnMap);

const switchFilters = computed(() =>
  props.filters.filter((f) => f.kind === "switch")
);
const checkboxFilters = computed(() =>
  props.filters.filter((f) => f.kind === "checkbox")
);
const sliderFilters = computed(() =>
  props.filters.filter((f) => f.kind === "slider")
);

// Event handlers
function handleCheckboxChange(
  filterId: string,
  value: any,
  checked: boolean
): void {
  const newValue = filterHelpers.computeCheckboxChange(
    filterId,
    value,
    checked
  );
  emit("filter-change", filterId, newValue);
}

function handleExcludeMissingChange(
  filterId: string,
  value: boolean | null
): void {
  excludeMissingValues.value[filterId] = value ?? false;
  const currentValue = props.activeFilters.get(filterId);
  emit("filter-change", filterId, {
    value: currentValue,
    excludeMissing: value ?? false,
  });
}

/** Reset layers panel to defaults */
function resetLayers(): void {
  layersPanelRef.value?.resetToDefaults();
}

// Expose methods for parent components
defineExpose({
  resetLayers,
});
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
  color: #fff;
}

@media only screen and (max-width: 767px) {
  .map-sidebar {
    width: 100%;
    height: 800px;
    border-top: 5px solid #868b8e;
    border-left-width: 0px;
  }
}

.sidebar-overlay {
  background-color: rgba(53, 61, 66, 0.5);
}

.sidebar-header {
  text-align: center;
  padding: 5px;
  border-bottom: 5px solid #868b8e;
}

.data-size-section {
  padding: 0 16px;
}

.data-size-message {
  font-style: italic;
  padding-bottom: 5px;
}

.highlight-count {
  color: #7ab5e5;
  font-weight: 500;
}

.sidebar-note {
  font-size: 0.8rem;
  font-style: italic;
  padding-top: 0.25rem;
  color: rgba(255, 255, 255, 0.7);
}

.buttons-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px 24px;
}

.action-button {
  width: 100%;
  max-width: 300px;
}

.sidebar-inner-content {
  background-color: #353d42;
  overflow-y: auto;
  flex: 1;
}

.sidebar-section {
  padding: 16px 24px !important;
}

.section-title {
  font-size: 1.6rem;
  font-weight: 500;
  text-align: center;
  margin-bottom: 0.5rem;
}

.section-divider {
  border-top: 2px solid #7ab5e5 !important;
  opacity: 1 !important;
  max-width: 150px;
  margin: 0 auto 16px auto !important;
}

/* Vuetify overrides - Expansion panels */
:deep(.v-expansion-panels) {
  --v-expansion-panel-elevation: 0;
}

:deep(.v-expansion-panel) {
  background-color: #353d42 !important;
  margin-top: 0 !important;
  border-top: 1px solid rgba(255, 255, 255, 0.2) !important;
}

:deep(.v-expansion-panel:last-child) {
  border-bottom: 1px solid rgba(255, 255, 255, 0.2) !important;
}

:deep(.v-expansion-panel-title) {
  font-size: 1.1rem !important;
  min-height: 48px !important;
}

:deep(.v-expansion-panel-title__overlay) {
  display: none !important;
}

/* Vuetify overrides - Form controls */
:deep(.v-checkbox .v-label),
:deep(.v-switch .v-label) {
  color: #fff;
}

:deep(.v-select .v-field__input) {
  color: #fff;
}

:deep(.v-slider-thumb__label) {
  font-size: 1rem;
}
</style>
