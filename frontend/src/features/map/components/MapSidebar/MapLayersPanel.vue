<template>
  <div class="map-layers-panel">
    <div class="section-title">Map Layers</div>
    <v-divider class="section-divider" />

    <!-- Layer toggle checkboxes -->
    <CheckboxGroup
      :items="toggleableLayerNames"
      :selected-values="selectedLayers"
      :ncol="1"
      :disabled="selectedOverlay !== null"
      @change="handleLayerToggle"
      @only="handleLayerOnly"
    />

    <!-- Aggregation Layer Dropdown -->
    <div v-if="overlayLayerNames.length > 0" class="overlay-section mt-4">
      <v-select
        v-model="selectedOverlay"
        :items="overlayLayerNames"
        label="Aggregation Layer"
        hint="Choose a geography to aggregate the data by"
        persistent-hint
        clearable
        variant="outlined"
        density="compact"
      />

      <div class="opacity-control mt-2">
        <v-slider
          v-model="overlayOpacity"
          :disabled="selectedOverlay === null"
          :min="0"
          :max="50"
          :step="1"
          label="Opacity"
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

import { ref, watch } from "vue";
import { CheckboxGroup } from "./filters";

const props = defineProps<{
  /** Names of toggleable layers */
  toggleableLayerNames: string[];
  /** Names of overlay layers for aggregation */
  overlayLayerNames: string[];
  /** Default toggled layer names */
  defaultToggledLayerNames: string[];
}>();

const emit = defineEmits<{
  /** Emitted when a layer's visibility changes */
  "layer-change": [layerName: string, visible: boolean];
  /** Emitted when overlay layer changes */
  "overlay-change": [layerName: string | null];
  /** Emitted when overlay opacity changes */
  "opacity-change": [layerName: string, opacity: number];
}>();

// Local state
const selectedLayers = ref<string[]>([...props.defaultToggledLayerNames]);
const selectedOverlay = ref<string | null>(null);
const overlayOpacity = ref(50);

/** Handle layer checkbox toggle */
function handleLayerToggle(layerName: string, visible: boolean): void {
  if (visible) {
    selectedLayers.value = [...selectedLayers.value, layerName];
  } else {
    selectedLayers.value = selectedLayers.value.filter((l) => l !== layerName);
  }
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

// Watch for overlay changes
watch(selectedOverlay, (newValue) => {
  emit("overlay-change", newValue);
});

watch(overlayOpacity, (newValue) => {
  if (selectedOverlay.value) {
    emit("opacity-change", selectedOverlay.value, newValue / 100);
  }
});

/** Reset layers and overlay to defaults */
function resetToDefaults(): void {
  selectedLayers.value = [...props.defaultToggledLayerNames];
  selectedOverlay.value = null;
  overlayOpacity.value = 50;
}

// Expose methods for parent components
defineExpose({
  resetToDefaults,
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

.overlay-section {
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

.opacity-slider :deep(.v-slider-track__fill) {
  background-color: #7ab5e5 !important;
}

.opacity-slider :deep(.v-slider-thumb) {
  color: #7ab5e5 !important;
}
</style>
