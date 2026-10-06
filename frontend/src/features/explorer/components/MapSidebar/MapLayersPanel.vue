<template>
  <div class="map-layers-panel">
    <div class="section-title">Map Layers</div>
    <v-divider class="section-divider" />

    <!-- Layer toggle checkboxes -->
    <CheckboxGroup
      :items="toggleableLayerNames"
      :selected-values="selectedLayers"
      :ncol="1"
      :disabled="localSelectedChoropleth !== null"
      @change="handleLayerToggle"
      @only="handleLayerOnly"
    />

    <!-- Choropleth Layer Dropdown -->
    <div v-if="choroplethLayerNames.length > 0" class="choropleth-section mt-4">
      <v-select
        v-model="localSelectedChoropleth"
        :items="choroplethLayerNames"
        label="Choropleth Layer"
        hint="Choose a geography to aggregate the data by"
        persistent-hint
        clearable
        variant="outlined"
        density="compact"
      />

      <div
        v-if="localSelectedChoropleth !== null"
        class="opacity-control mt-2"
      >
        <v-slider
          v-model="choroplethOpacity"
          :min="0"
          :max="50"
          :step="1"
          label="Opacity"
          aria-label="Choropleth layer opacity"
          hide-details
          class="opacity-slider"
          color="primary"
          track-color="grey-lighten-1"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * MapLayersPanel Component
 *
 * Panel for toggling map layers and selecting aggregation overlays.
 * Reuses CheckboxGroup for the layer toggle checkboxes.
 *
 * Features:
 * - Hover to show "only" link that selects just that layer
 * - Aggregation layer dropdown with opacity control
 *
 * @component
 */

import { ref, watch, onMounted } from "vue";
import { CheckboxGroup } from "./filters";
import { track } from "@/shared/analytics";

const props = defineProps<{
  /** Names of toggleable layers */
  toggleableLayerNames: string[];
  /** Names of choropleth layers for geographic aggregation */
  choroplethLayerNames: string[];
  /** Default toggled layer names (used for reset) */
  defaultToggledLayerNames: string[];
  /** Initial active layers from URL state */
  initialActiveLayers?: string[];
  /** Selected choropleth layer from URL state */
  selectedChoropleth?: string | null;
}>();

const emit = defineEmits<{
  /** Emitted when a layer's visibility changes */
  "layer-change": [layerName: string, visible: boolean];
  /** Emitted when choropleth layer changes */
  "choropleth-change": [layerName: string | null];
  /** Emitted when choropleth opacity changes */
  "opacity-change": [layerName: string, opacity: number];
}>();

// Local state - initialize from initialActiveLayers if provided, else defaults
const selectedLayers = ref<string[]>(
  props.initialActiveLayers && props.initialActiveLayers.length > 0
    ? [...props.initialActiveLayers]
    : [...props.defaultToggledLayerNames],
);
const localSelectedChoropleth = ref<string | null>(
  props.selectedChoropleth ?? null,
);
const choroplethOpacity = ref(50);

/** Handle layer checkbox toggle */
function handleLayerToggle(layerName: string, visible: boolean): void {
  if (visible) {
    selectedLayers.value = [...selectedLayers.value, layerName];
  } else {
    selectedLayers.value = selectedLayers.value.filter((l) => l !== layerName);
  }

  // Track layer change
  track("map_layer_changed", {
    layer: layerName,
    visible,
  });

  emit("layer-change", layerName, visible);
}

/** Handle "only" click - show only the selected layer */
function handleLayerOnly(layerName: string): void {
  // Hide all currently selected layers except the target
  const previousLayers = [...selectedLayers.value];
  selectedLayers.value = [layerName];

  // Emit change events for layers being hidden
  for (const layer of previousLayers) {
    if (layer !== layerName) {
      emit("layer-change", layer, false);
    }
  }
  // Emit change event for the target layer (ensure it's shown)
  if (!previousLayers.includes(layerName)) {
    emit("layer-change", layerName, true);
  }
}

// Watch for choropleth changes
watch(localSelectedChoropleth, (newValue, oldValue) => {
  // Track choropleth layer change
  track("choropleth_changed", {
    layer: newValue,
    previous_layer: oldValue,
  });

  emit("choropleth-change", newValue);
});

watch(choroplethOpacity, (newValue) => {
  if (localSelectedChoropleth.value) {
    emit("opacity-change", localSelectedChoropleth.value, newValue / 100);
  }
});

/** Reset layers and choropleth to defaults */
function resetToDefaults(): void {
  selectedLayers.value = [...props.defaultToggledLayerNames];
  localSelectedChoropleth.value = null;
  choroplethOpacity.value = 50;
}

// Expose methods for parent components
defineExpose({
  resetToDefaults,
});

// Emit initial choropleth change if set from URL
onMounted(() => {
  if (props.selectedChoropleth) {
    emit("choropleth-change", props.selectedChoropleth);
  }
});
</script>

<style scoped>
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

.choropleth-section {
  margin-top: 24px;
}

.opacity-control {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 75%;
}

.opacity-slider {
  flex: 1;
}

.opacity-slider :deep(.v-label) {
  color: #ffffff;
  opacity: 1;
}

.opacity-slider :deep(.v-slider-track__fill) {
  background-color: #7ab5e5 !important;
}

.opacity-slider :deep(.v-slider-thumb) {
  color: #7ab5e5 !important;
}
</style>
