<template>
  <div v-if="visible" class="map-legend">
    <div class="legend-label">{{ options.title }}</div>
    <div class="legend-bar-container">
      <svg ref="svgRef" :width="width" :height="height">
        <defs>
          <linearGradient
            id="legend-gradient"
            ref="gradientRef"
          ></linearGradient>
        </defs>
        <rect
          class="legend-bar"
          :x="0"
          :y="0"
          :width="width"
          :height="barHeight"
          :rx="3"
          fill="url(#legend-gradient)"
        />
      </svg>
      <div class="legend-ticks">
        <span class="tick-min">{{ formatNumber(options.domain[0]) }}</span>
        <span class="tick-max">{{ formatNumber(options.domain[1]) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * MapLegend Component
 *
 * Compact color scale legend for aggregated map layers.
 * Styled to match the address search bar aesthetic.
 *
 * @component
 */

import { ref, computed, nextTick, watch } from "vue";
import { scaleLinear } from "d3-scale";
import { select } from "d3-selection";
import { format } from "d3-format";
import * as d3ScaleChromatic from "d3-scale-chromatic";

// Props
interface Props {
  /** Width of the legend bar */
  width?: number;
  /** Height of the color bar */
  barHeight?: number;
}

const props = withDefaults(defineProps<Props>(), {
  width: 160,
  barHeight: 8,
});

// Legend options
interface LegendOptions {
  colorScheme: string;
  range: [number, number];
  domain: [number, number];
  title: string;
}

// State
const visible = ref(false);
const options = ref<LegendOptions>({
  colorScheme: "Reds",
  range: [0, 1],
  domain: [0, 1],
  title: "Total",
});

// Refs
const svgRef = ref<SVGSVGElement | null>(null);
const gradientRef = ref<SVGLinearGradientElement | null>(null);

// Computed
const height = computed(() => props.barHeight);

const colorScale = computed(() =>
  scaleLinear().domain(options.value.domain).range(options.value.range)
);

// Format numbers compactly
function formatNumber(n: number): string {
  if (n >= 1000) {
    return format(".2s")(n);
  }
  return format(",d")(n);
}

// Methods
function show(newOptions: LegendOptions): void {
  visible.value = true;
  options.value = { ...newOptions };

  nextTick(() => {
    updateGradient();
  });
}

function hide(): void {
  visible.value = false;
}

function updateGradient(): void {
  if (!svgRef.value) return;

  const key =
    `interpolate${options.value.colorScheme}` as keyof typeof d3ScaleChromatic;
  const interpolator = d3ScaleChromatic[key] as (t: number) => string;

  if (!interpolator) {
    console.error(`Color scheme ${options.value.colorScheme} not found`);
    return;
  }

  // Update gradient stops
  const gradient = select(svgRef.value).select("#legend-gradient");
  gradient.selectAll("stop").remove();

  const numStops = 10;
  for (let i = 0; i <= numStops; i++) {
    const t = i / numStops;
    const colorValue =
      options.value.range[0] +
      t * (options.value.range[1] - options.value.range[0]);
    gradient
      .append("stop")
      .attr("offset", `${t * 100}%`)
      .attr("stop-color", interpolator(colorValue));
  }
}

// Watch for options changes
watch(options, () => {
  if (visible.value) {
    nextTick(() => updateGradient());
  }
});

// Expose methods
defineExpose({
  show,
  hide,
});
</script>

<style scoped>
.map-legend {
  position: absolute;
  bottom: 50px;
  left: 10px;
  z-index: 1000;
  background: rgba(40, 46, 51, 0.97);
  border: 2px solid rgba(122, 181, 229, 0.4);
  border-radius: 6px;
  padding: 8px 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.4);
}

.legend-label {
  font-size: 11px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.7);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.legend-bar-container {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.legend-bar {
  display: block;
}

.legend-ticks {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.85);
  font-variant-numeric: tabular-nums;
}

.tick-min,
.tick-max {
  font-weight: 500;
}
</style>
