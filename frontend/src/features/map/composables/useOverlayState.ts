/**
 * useOverlayState Composable
 *
 * Manages overlay layer state and toggleable layer visibility.
 * Handles the interaction between choropleth overlays and point layers.
 *
 * When an overlay is selected:
 * - Current toggleable layers are saved
 * - Only the overlay layer is shown
 *
 * When an overlay is cleared:
 * - Saved toggleable layers are restored
 *
 * @module useOverlayState
 */

import { ref, computed } from "vue";
import type { ComputedRef } from "vue";
import { useRoute } from "vue-router";

interface UseOverlayStateOptions {
  toggleableLayerNames: ComputedRef<string[]>;
  overlayLayerNames: ComputedRef<string[]>;
  defaultToggledLayerNames: ComputedRef<string[]>;
  urlIdToLayerName: (urlId: string, allLayerNames: string[]) => string | null;
}

/**
 * Composable for managing overlay and layer state.
 *
 * @param options - Configuration options
 * @returns Overlay state and handlers
 */
export function useOverlayState({
  toggleableLayerNames,
  overlayLayerNames,
  defaultToggledLayerNames,
  urlIdToLayerName,
}: UseOverlayStateOptions) {
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
        ...overlayLayerNames.value,
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
   * Parse initial overlay from URL (if layers param contains an overlay layer).
   */
  function getInitialOverlayFromUrl(): string | null {
    const layersParam = route.query.layers;

    if (layersParam && typeof layersParam === "string") {
      const urlIds = layersParam
        .split(",")
        .map((id) => id.trim())
        .filter(Boolean);

      // Find the first URL ID that matches an overlay layer name
      for (const urlId of urlIds) {
        const matchedName = urlIdToLayerName(urlId, overlayLayerNames.value);
        if (matchedName) {
          return matchedName;
        }
      }
    }
    return null;
  }

  // Active layers (names of layers to display on the map)
  const activeLayers = ref<string[]>(getInitialLayersFromUrl());

  // Track currently selected overlay layer
  const currentOverlay = ref<string | null>(getInitialOverlayFromUrl());

  // Track saved toggleable layers (to restore when overlay is cleared)
  const savedToggleableLayers = ref<string[]>(
    currentOverlay.value ? [...defaultToggledLayerNames.value] : []
  );

  // Compute the toggleable layers for checkbox state
  const initialToggleableLayers = computed(() => {
    if (currentOverlay.value) {
      // Overlay is active - show saved toggleable layers
      return savedToggleableLayers.value.length > 0
        ? savedToggleableLayers.value
        : defaultToggledLayerNames.value;
    }
    // No overlay - filter activeLayers to only include toggleable layers
    return activeLayers.value.filter((l) =>
      toggleableLayerNames.value.includes(l)
    );
  });

  /**
   * Handle layer visibility change.
   * When overlay is active, updates savedToggleableLayers instead of activeLayers.
   */
  function handleLayerChange(layerName: string, visible: boolean): void {
    // When overlay is active, update savedToggleableLayers
    if (currentOverlay.value) {
      if (visible) {
        if (!savedToggleableLayers.value.includes(layerName)) {
          savedToggleableLayers.value = [
            ...savedToggleableLayers.value,
            layerName,
          ];
        }
      } else {
        savedToggleableLayers.value = savedToggleableLayers.value.filter(
          (l) => l !== layerName
        );
      }
      return;
    }

    // No overlay - update activeLayers directly
    if (visible) {
      if (!activeLayers.value.includes(layerName)) {
        activeLayers.value = [...activeLayers.value, layerName];
      }
    } else {
      activeLayers.value = activeLayers.value.filter((l) => l !== layerName);
    }
  }

  /**
   * Handle overlay layer change.
   * When an overlay is selected, toggleable layers are hidden and saved.
   * When overlay is cleared, toggleable layers are restored.
   */
  function handleOverlayChange(layerName: string | null): void {
    // Remove current overlay from active layers (if any)
    if (currentOverlay.value) {
      activeLayers.value = activeLayers.value.filter(
        (l) => l !== currentOverlay.value
      );
    }

    if (layerName) {
      // Selecting an overlay - save current toggleable layers and remove them
      const currentToggleable = activeLayers.value.filter((l) =>
        toggleableLayerNames.value.includes(l)
      );
      if (currentToggleable.length > 0) {
        savedToggleableLayers.value = currentToggleable;
      }
      // Remove toggleable layers, add overlay
      activeLayers.value = [layerName];
    } else {
      // Clearing overlay - restore saved toggleable layers
      if (savedToggleableLayers.value.length > 0) {
        activeLayers.value = [...savedToggleableLayers.value];
        savedToggleableLayers.value = [];
      } else {
        // Fallback to defaults if nothing was saved
        activeLayers.value = [...defaultToggledLayerNames.value];
      }
    }

    // Update current overlay
    currentOverlay.value = layerName;
  }

  /**
   * Reset layers to defaults.
   * Called when year changes to reset layer selection.
   */
  function resetLayers(): void {
    activeLayers.value = [...defaultToggledLayerNames.value];
    currentOverlay.value = null;
    savedToggleableLayers.value = [];
  }

  return {
    activeLayers,
    currentOverlay,
    savedToggleableLayers,
    initialToggleableLayers,
    handleLayerChange,
    handleOverlayChange,
    resetLayers,
  };
}
