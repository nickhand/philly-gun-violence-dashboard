/**
 * Map tooltips composable.
 *
 * Handles MapLibre GL popup creation and management for layer tooltips.
 * Supports "pinning" tooltips on click for text selection/copying.
 *
 * @module useMapTooltips
 */

import { onBeforeUnmount, type Ref } from "vue";
import maplibregl, {
  type Map as MapLibreMap,
  type Popup,
  type MapLayerMouseEvent,
} from "maplibre-gl";
import type { TooltipConfig } from "../types";
import { layerNameToId } from "./mapUtils";

/** Event handler function type */
type EventHandler = (e: MapLayerMouseEvent) => void;
type LeaveHandler = () => void;

/**
 * Composable for managing map tooltips using MapLibre GL Popups.
 *
 * Features:
 * - Hover tooltips that follow the mouse
 * - Click-to-pin functionality for copying text
 * - Text selection enabled in pinned tooltips
 *
 * @param mapInstance - Reactive ref to map instance
 * @param setCursor - Function to set cursor style
 * @returns Tooltip management methods
 */
export function useMapTooltips(
  mapInstance: Ref<MapLibreMap | null>,
  setCursor: (cursor: string) => void
) {
  // Track active popups per layer for cleanup
  const activePopups = new Map<string, Popup>();

  // Track pinned popup (only one can be pinned at a time)
  let pinnedPopup: Popup | null = null;
  let pinnedLayerId: string | null = null;

  // Track event handlers for proper cleanup
  const eventHandlers = new Map<
    string,
    {
      enter?: EventHandler;
      move?: EventHandler;
      leave?: LeaveHandler;
      click?: EventHandler;
    }
  >();

  /**
   * Check if mouse is over the popup element.
   */
  function isMouseOverPopup(popup: Popup): boolean {
    const popupEl = popup.getElement();
    if (!popupEl) return false;
    return popupEl.matches(":hover");
  }

  /**
   * Create a pinned popup with close button.
   */
  function createPinnedPopup(
    map: MapLibreMap,
    lngLat: maplibregl.LngLat,
    html: string
  ): Popup {
    // Remove existing pinned popup
    if (pinnedPopup) {
      pinnedPopup.remove();
      pinnedPopup = null;
      pinnedLayerId = null;
    }

    const popup = new maplibregl.Popup({
      closeButton: true,
      closeOnClick: false,
      className: "map-tooltip-popup map-tooltip-popup--pinned",
      maxWidth: "320px",
    });

    popup.setLngLat(lngLat).setHTML(html).addTo(map);

    // Track as pinned
    pinnedPopup = popup;

    // Clean up when closed
    popup.on("close", () => {
      if (pinnedPopup === popup) {
        pinnedPopup = null;
        pinnedLayerId = null;
      }
    });

    return popup;
  }

  /**
   * Create a tooltip popup for a layer.
   *
   * @param layerName - The layer name (will be converted to layer ID)
   * @param config - Tooltip configuration with formatter and trigger
   */
  function addTooltip(layerName: string, config: TooltipConfig): void {
    const map = mapInstance.value;
    if (!map) return;

    const layerId = layerNameToId(layerName);

    // Remove existing tooltip for this layer
    removeTooltip(layerName);

    // Create hover popup (no close button, follows mouse)
    const hoverPopup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      className: "map-tooltip-popup",
      maxWidth: "320px",
    });

    activePopups.set(layerId, hoverPopup);

    const handlers: {
      enter?: EventHandler;
      move?: EventHandler;
      leave?: LeaveHandler;
      click?: EventHandler;
    } = {};

    if (config.on === "mouseenter") {
      const onMouseEnter: EventHandler = (e) => {
        // Don't show hover tooltip if we have a pinned one for this layer
        if (pinnedPopup && pinnedLayerId === layerId) return;

        const features = e.features;
        if (!features?.length) return;

        const props = features[0].properties ?? {};

        setCursor("pointer");
        hoverPopup
          .setLngLat(e.lngLat)
          .setHTML(config.formatter(props))
          .addTo(map);
      };

      const onMouseLeave: LeaveHandler = () => {
        // Don't hide if mouse is over the popup itself
        if (isMouseOverPopup(hoverPopup)) return;

        setCursor("");
        hoverPopup.remove();
      };

      const onClick: EventHandler = (e) => {
        const features = e.features;
        if (!features?.length) return;

        const props = features[0].properties ?? {};

        // Remove hover popup and create pinned one
        hoverPopup.remove();
        pinnedLayerId = layerId;
        createPinnedPopup(map, e.lngLat, config.formatter(props));
      };

      map.on("mouseenter", layerId, onMouseEnter);
      map.on("mouseleave", layerId, onMouseLeave);
      map.on("click", layerId, onClick);

      handlers.enter = onMouseEnter;
      handlers.leave = onMouseLeave;
      handlers.click = onClick;
    } else if (config.on === "mousemove") {
      const onMouseMove: EventHandler = (e) => {
        // Don't show hover tooltip if we have a pinned one for this layer
        if (pinnedPopup && pinnedLayerId === layerId) return;

        const features = e.features;
        if (!features?.length) return;

        const props = features[0].properties ?? {};

        hoverPopup
          .setLngLat(e.lngLat)
          .setHTML(config.formatter(props))
          .addTo(map);
      };

      const onMouseLeave: LeaveHandler = () => {
        hoverPopup.remove();
      };

      const onClick: EventHandler = (e) => {
        const features = e.features;
        if (!features?.length) return;

        const props = features[0].properties ?? {};

        // Remove hover popup and create pinned one
        hoverPopup.remove();
        pinnedLayerId = layerId;
        createPinnedPopup(map, e.lngLat, config.formatter(props));
      };

      map.on("mousemove", layerId, onMouseMove);
      map.on("mouseleave", layerId, onMouseLeave);
      map.on("click", layerId, onClick);

      handlers.move = onMouseMove;
      handlers.leave = onMouseLeave;
      handlers.click = onClick;
    } else if (config.on === "click") {
      // Click-only mode - always creates pinned popup
      const onClick: EventHandler = (e) => {
        const features = e.features;
        if (!features?.length) return;

        const props = features[0].properties ?? {};
        pinnedLayerId = layerId;
        createPinnedPopup(map, e.lngLat, config.formatter(props));
      };

      map.on("click", layerId, onClick);
      handlers.click = onClick;
    }

    eventHandlers.set(layerId, handlers);
  }

  /**
   * Remove tooltip from a layer.
   */
  function removeTooltip(layerName: string): void {
    const map = mapInstance.value;
    if (!map) return;

    const layerId = layerNameToId(layerName);

    // Remove hover popup
    const popup = activePopups.get(layerId);
    if (popup) {
      popup.remove();
      activePopups.delete(layerId);
    }

    // Remove pinned popup if it belongs to this layer
    if (pinnedPopup && pinnedLayerId === layerId) {
      pinnedPopup.remove();
      pinnedPopup = null;
      pinnedLayerId = null;
    }

    // Remove event handlers
    const handlers = eventHandlers.get(layerId);
    if (handlers) {
      if (handlers.enter) {
        map.off("mouseenter", layerId, handlers.enter);
      }
      if (handlers.move) {
        map.off("mousemove", layerId, handlers.move);
      }
      if (handlers.leave) {
        map.off("mouseleave", layerId, handlers.leave);
      }
      if (handlers.click) {
        map.off("click", layerId, handlers.click);
      }
      eventHandlers.delete(layerId);
    }
  }

  /**
   * Clean up all tooltips.
   */
  function cleanup(): void {
    for (const popup of activePopups.values()) {
      popup.remove();
    }
    activePopups.clear();

    if (pinnedPopup) {
      pinnedPopup.remove();
      pinnedPopup = null;
      pinnedLayerId = null;
    }

    eventHandlers.clear();
  }

  // Cleanup on unmount
  onBeforeUnmount(() => {
    cleanup();
  });

  return {
    addTooltip,
    removeTooltip,
    cleanup,
  };
}
