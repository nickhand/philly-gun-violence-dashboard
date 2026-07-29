<template>
  <div class="histogram-chart" ref="containerRef">
    <svg
      :width="chartWidth"
      :height="height"
      class="histogram-svg"
      aria-hidden="true"
      focusable="false"
    >
      <!-- Bars -->
      <g class="bars">
        <rect
          v-for="(bin, i) in bins"
          :key="i"
          :x="getBarX(bin)"
          :y="getBarY(bin)"
          :width="barWidth"
          :height="getBarHeight(bin)"
          :fill="getBarColor(bin)"
          class="histogram-bar"
        />
      </g>
      <!-- Selection range indicator lines -->
      <line
        :x1="getLowerLineX()"
        :y1="0"
        :x2="getLowerLineX()"
        :y2="height"
        stroke="white"
        stroke-width="2"
      />
      <line
        :x1="getUpperLineX()"
        :y1="0"
        :x2="getUpperLineX()"
        :y2="height"
        stroke="white"
        stroke-width="2"
      />
    </svg>
  </div>
</template>

<script setup lang="ts">
/**
 * SliderHistogramChart Component
 *
 * Displays a histogram chart above slider filters to show data distribution.
 * Bars within the selected range are highlighted, bars outside are grayed out.
 *
 * @component
 */

import { ref, computed, onMounted, onUnmounted } from "vue";
import { scaleLinear } from "d3-scale";
import type { HistogramBin } from "@/features/explorer/types";

const props = withDefaults(
  defineProps<{
    /** Histogram bin data */
    bins: HistogramBin[];
    /** Current slider lower bound */
    lower: number;
    /** Current slider upper bound */
    upper: number;
    /** Data minimum value */
    min: number;
    /** Data maximum value */
    max: number;
    /** Chart height in pixels */
    height?: number;
  }>(),
  {
    height: 60,
  },
);

// Container ref for responsive width
const containerRef = ref<HTMLElement | null>(null);
const containerWidth = ref(200);

// Responsive width handling
let resizeObserver: ResizeObserver | null = null;

onMounted(() => {
  if (containerRef.value) {
    containerWidth.value = containerRef.value.clientWidth;

    resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        containerWidth.value = entry.contentRect.width;
      }
    });
    resizeObserver.observe(containerRef.value);
  }
});

onUnmounted(() => {
  resizeObserver?.disconnect();
});

// Chart dimensions
const chartWidth = computed(() => containerWidth.value);
const padding = { left: 4, right: 4, top: 4, bottom: 4 };

// Calculate bar width based on number of bins
const barWidth = computed(() => {
  if (props.bins.length === 0) return 0;
  const availableWidth = chartWidth.value - padding.left - padding.right;
  if (availableWidth <= 0) return 0;
  // Leave small gaps between bars (80% of slot width)
  return Math.max(0, (availableWidth / props.bins.length) * 0.8);
});

// X scale: maps data values to pixel positions
const xScale = computed(() => {
  return scaleLinear()
    .domain([props.min, props.max])
    .range([padding.left, chartWidth.value - padding.right]);
});

// Y scale: maps bin counts to pixel positions
const yScale = computed(() => {
  const maxCount = Math.max(...props.bins.map((b) => b.length), 1);
  return scaleLinear()
    .domain([0, maxCount])
    .range([props.height - padding.bottom, padding.top]);
});

// Helper functions for rendering
function getBarX(bin: HistogramBin): number {
  // Center the bar in its slot
  const slotWidth =
    (chartWidth.value - padding.left - padding.right) / props.bins.length;
  const binIndex = props.bins.indexOf(bin);
  return padding.left + binIndex * slotWidth + (slotWidth - barWidth.value) / 2;
}

function getBarY(bin: HistogramBin): number {
  return yScale.value(bin.length);
}

function getBarHeight(bin: HistogramBin): number {
  return Math.max(0, props.height - padding.bottom - yScale.value(bin.length));
}

function getBarColor(bin: HistogramBin): string {
  // Gray out bars outside the selected range
  const binCenter = (bin.x0 + bin.x1) / 2;
  if (binCenter < props.lower || binCenter > props.upper) {
    return "#aaa";
  }
  return "#7ab5e5";
}

function getLowerLineX(): number {
  return xScale.value(props.lower);
}

function getUpperLineX(): number {
  return xScale.value(props.upper);
}
</script>

<style scoped>
.histogram-chart {
  width: 100%;
  margin-bottom: 8px;
}

.histogram-svg {
  display: block;
}

.histogram-bar {
  transition: fill 0.15s ease;
}
</style>
