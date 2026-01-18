<template>
  <div
    class="search-marker"
    :style="positionStyle"
    aria-label="Searched location marker"
  >
    <div class="marker-pin">
      <!-- Crosshair/target marker matching theme -->
      <svg viewBox="0 0 48 48" width="32" height="32">
        <!-- Outer ring with glow -->
        <circle
          cx="24"
          cy="24"
          r="18"
          fill="none"
          stroke="#7ab5e5"
          stroke-width="2"
          opacity="0.4"
        />
        <!-- Inner ring -->
        <circle
          cx="24"
          cy="24"
          r="12"
          fill="none"
          stroke="#7ab5e5"
          stroke-width="2.5"
        />
        <!-- Center dot -->
        <circle cx="24" cy="24" r="4" fill="#7ab5e5" />
        <!-- Crosshairs -->
        <line
          x1="24"
          y1="6"
          x2="24"
          y2="12"
          stroke="#7ab5e5"
          stroke-width="2"
          stroke-linecap="round"
        />
        <line
          x1="24"
          y1="36"
          x2="24"
          y2="42"
          stroke="#7ab5e5"
          stroke-width="2"
          stroke-linecap="round"
        />
        <line
          x1="6"
          y1="24"
          x2="12"
          y2="24"
          stroke="#7ab5e5"
          stroke-width="2"
          stroke-linecap="round"
        />
        <line
          x1="36"
          y1="24"
          x2="42"
          y2="24"
          stroke="#7ab5e5"
          stroke-width="2"
          stroke-linecap="round"
        />
      </svg>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * SearchMarker Component
 *
 * A crosshair/target marker displayed at a searched address location.
 * Positioned absolutely within the map container using screen coordinates.
 *
 * @component
 */

import { computed } from "vue";

const props = defineProps<{
  /** Screen X coordinate (pixels from left) */
  x: number;
  /** Screen Y coordinate (pixels from top) */
  y: number;
}>();

// Center the 32x32 crosshair on the point
const positionStyle = computed(() => ({
  transform: `translate(${props.x - 16}px, ${props.y - 16}px)`,
}));
</script>

<style scoped>
.search-marker {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 5;
  pointer-events: none;
  filter: drop-shadow(0 0 8px rgba(122, 181, 229, 0.6));
}

.marker-pin {
  animation: pulse-in 0.4s ease-out forwards;
}

@keyframes pulse-in {
  0% {
    transform: scale(0.3);
    opacity: 0;
  }
  60% {
    transform: scale(1.1);
    opacity: 1;
  }
  100% {
    transform: scale(1);
    opacity: 1;
  }
}
</style>
