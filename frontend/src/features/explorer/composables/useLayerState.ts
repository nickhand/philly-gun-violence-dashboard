/**
 * useLayerState Composable
 *
 * Manages layer visibility state including toggleable layers and choropleth layers.
 * Handles the interaction between choropleth (boundary fill) layers and point layers.
 *
 * When a choropleth layer is selected:
 * - Current toggleable layers are saved
 * - Only the choropleth layer is shown
 *
 * When a choropleth layer is cleared:
 * - Saved toggleable layers are restored
 *
 * @module useLayerState
 */

import { ref, computed } from "vue";
import type { ComputedRef } from "vue";
import { useRoute } from "vue-router";

interface UseLayerStateOptions {
  toggleableLayerNames: ComputedRef<string[]>;
  choroplethLayerNames: ComputedRef<string[]>;
  defaultToggledLayerNames: ComputedRef<string[]>;
  urlIdToLayerName: (urlId: string, allLayerNames: string[]) => string | null;
}

/**
 * Composable for managing layer visibility state.
 *
 * @param options - Configuration options
 * @returns Layer state and handlers
 */
export function useLayerState({
  toggleableLayerNames,
  choroplethLayerNames,
  defaultToggledLayerNames,
  urlIdToLayerName,
}: UseLayerStateOptions) {
  const route = useRoute();

  /**
   * Parse initial layers from URL query parameter.
   * Converts URL IDs (e.g., "point-locations") to layer names (e.g., "Point locations").
   */
  function getInitialLayersFromUrl(): string[] {
    const layersParam = route.query.layers;

    if (layersParam && typeof layersParam === "string") {
      const allLayerNames = [
        ...toggleableLayerNames.value,
        ...choroplethLayerNames.value,
      ];

      const layers = layersParam
        .split(",")
        .map((id) => id.trim())
        .filter(Boolean)
        .map((id) => urlIdToLayerName(id, allLayerNames))
        .filter((name): name is string => name !== null);

      if (layers.length > 0) {
        return layers;
      }
    }
    // Default to Point locations if no URL param
    return ["Point locations"];
  }

  /**
   * Parse initial choropleth layer from URL (if layers param contains one).
   */
  function getInitialChoroplethFromUrl(): string | null {
    const layersParam = route.query.layers;

    if (layersParam && typeof layersParam === "string") {
      const urlIds = layersParam
        .split(",")
        .map((id) => id.trim())
        .filter(Boolean);

      // Find the first URL ID that matches a choropleth layer name
      for (const urlId of urlIds) {
        const matchedName = urlIdToLayerName(urlId, choroplethLayerNames.value);
        if (matchedName) {
          return matchedName;
        }
      }
    }
    return null;
  }

  // Active layers (names of layers to display on the map)
  const activeLayers = ref<string[]>(getInitialLayersFromUrl());

  // Track currently selected choropleth layer
  const selectedChoropleth = ref<string | null>(getInitialChoroplethFromUrl());

  // Track saved toggleable layers (to restore when choropleth is cleared)
  const savedToggleableLayers = ref<string[]>(
    selectedChoropleth.value ? [...defaultToggledLayerNames.value] : [],
  );

  // Compute the toggleable layers for checkbox state
  const initialToggleableLayers = computed(() => {
    if (selectedChoropleth.value) {
      // Choropleth is active - show saved toggleable layers
      return savedToggleableLayers.value.length > 0
        ? savedToggleableLayers.value
        : defaultToggledLayerNames.value;
    }
    // No choropleth - filter activeLayers to only include toggleable layers
    return activeLayers.value.filter((l) =>
      toggleableLayerNames.value.includes(l),
    );
  });

  /**
   * Handle layer visibility change.
   * When choropleth is active, updates savedToggleableLayers instead of activeLayers.
   */
  function handleLayerChange(layerName: string, visible: boolean): void {
    // When choropleth is active, update savedToggleableLayers
    if (selectedChoropleth.value) {
      if (visible) {
        if (!savedToggleableLayers.value.includes(layerName)) {
          savedToggleableLayers.value = [
            ...savedToggleableLayers.value,
            layerName,
          ];
        }
      } else {
        savedToggleableLayers.value = savedToggleableLayers.value.filter(
          (l) => l !== layerName,
        );
      }
      return;
    }

    // No choropleth - update activeLayers directly
    if (visible) {
      if (!activeLayers.value.includes(layerName)) {
        activeLayers.value = [...activeLayers.value, layerName];
      }
    } else {
      activeLayers.value = activeLayers.value.filter((l) => l !== layerName);
    }
  }

  /**
   * Handle choropleth layer change.
   * When a choropleth is selected, toggleable layers are hidden and saved.
   * When choropleth is cleared, toggleable layers are restored.
   */
  function handleChoroplethChange(layerName: string | null): void {
    // Remove current choropleth from active layers (if any)
    if (selectedChoropleth.value) {
      activeLayers.value = activeLayers.value.filter(
        (l) => l !== selectedChoropleth.value,
      );
    }

    if (layerName) {
      // Selecting a choropleth - save current toggleable layers and remove them
      const currentToggleable = activeLayers.value.filter((l) =>
        toggleableLayerNames.value.includes(l),
      );
      if (currentToggleable.length > 0) {
        savedToggleableLayers.value = currentToggleable;
      }
      // Remove toggleable layers, add choropleth
      activeLayers.value = [layerName];
    } else {
      // Clearing choropleth - restore saved toggleable layers
      if (savedToggleableLayers.value.length > 0) {
        activeLayers.value = [...savedToggleableLayers.value];
        savedToggleableLayers.value = [];
      } else {
        // Fallback to defaults if nothing was saved
        activeLayers.value = [...defaultToggledLayerNames.value];
      }
    }

    // Update selected choropleth
    selectedChoropleth.value = layerName;
  }

  /**
   * Reset layers to defaults.
   * Called when year changes to reset layer selection.
   */
  function resetLayers(): void {
    activeLayers.value = [...defaultToggledLayerNames.value];
    selectedChoropleth.value = null;
    savedToggleableLayers.value = [];
  }

  return {
    activeLayers,
    selectedChoropleth,
    savedToggleableLayers,
    initialToggleableLayers,
    handleLayerChange,
    handleChoroplethChange,
    resetLayers,
  };
}
