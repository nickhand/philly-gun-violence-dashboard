<template>
  <div v-if="visible" class="map-legend">
    <div class="map-legend__inner">
      <div class="legend-title">{{ options.title }}</div>
      <svg ref="svgRef" :width="width" :height="height">
        <g ref="canvasRef"></g>
      </svg>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * MapLegend Component
 *
 * Displays a color scale legend for aggregated map layers.
 * Uses d3 for rendering gradient and axis.
 *
 * @component
 */

import { ref, computed, nextTick, watch } from "vue";
import { scaleLinear } from "d3-scale";
import { axisBottom } from "d3-axis";
import { select } from "d3-selection";
import { format } from "d3-format";
import * as d3ScaleChromatic from "d3-scale-chromatic";

// Props
interface Props {
  /** Width of the legend */
  width?: number;
  /** Height of the color bar */
  barHeight?: number;
  /** Size of the axis ticks */
  tickSize?: number;
  /** D3 format string for tick labels */
  tickFormat?: string;
}

const props = withDefaults(defineProps<Props>(), {
  width: 250,
  barHeight: 15,
  tickSize: 12,
  tickFormat: ",.0f",
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
const canvasRef = ref<SVGGElement | null>(null);

// Margin
const margin = { right: 20, bottom: 40, left: 10, top: 5 };

// Computed
const height = computed(() => props.barHeight + margin.top + margin.bottom);

const colorScale = computed(() =>
  scaleLinear().domain(options.value.domain).range(options.value.range)
);

const axisScale = computed(() =>
  scaleLinear()
    .domain(colorScale.value.domain() as [number, number])
    .range([margin.left, props.width - margin.right])
);

// Methods
function show(newOptions: LegendOptions): void {
  visible.value = true;
  options.value = { ...newOptions };

  nextTick(() => {
    refreshLegend();
  });
}

function hide(): void {
  visible.value = false;
}

function refreshLegend(): void {
  removeLegend();
  addLegend();
}

function removeLegend(): void {
  if (!canvasRef.value) return;
  const svg = select(canvasRef.value);
  svg.selectAll("defs").remove();
  svg.selectAll("g").remove();
  svg.selectAll("rect").remove();
}

function addLegend(): void {
  if (!canvasRef.value) return;

  const svg = select(canvasRef.value);
  const defs = svg.append("defs");

  const linearGradient = defs
    .append("linearGradient")
    .attr("id", "map-legend-gradient");

  const key =
    `interpolate${options.value.colorScheme}` as keyof typeof d3ScaleChromatic;
  const interpolator = d3ScaleChromatic[key] as (t: number) => string;

  if (!interpolator) {
    console.error(`Color scheme ${options.value.colorScheme} not found`);
    return;
  }

  const ticks = colorScale.value.ticks(10);
  linearGradient
    .selectAll("stop")
    .data(
      ticks.map((t: number, i: number) => ({
        offset: `${(100 * i) / (ticks.length - 1)}%`,
        color: interpolator(colorScale.value(t) as number),
      }))
    )
    .enter()
    .append("stop")
    .attr("offset", (d: { offset: string; color: string }) => d.offset)
    .attr("stop-color", (d: { offset: string; color: string }) => d.color);

  // Color bar
  svg
    .append("rect")
    .attr("x", margin.left)
    .attr("y", margin.top)
    .attr("width", props.width - margin.right - margin.left)
    .attr("height", props.barHeight)
    .attr("stroke", "#fff")
    .attr("stroke-width", 1)
    .style("fill", "url(#map-legend-gradient)");

  // Axis
  const axisGroup = svg
    .append("g")
    .attr("class", "x-axis")
    .attr("transform", `translate(0,${margin.top + props.barHeight})`);

  axisGroup.call(
    axisBottom(axisScale.value)
      .tickValues(options.value.domain)
      .tickSize(props.tickSize)
      .tickFormat((d: unknown) => format(props.tickFormat)(d as number))
  );
}

// Watch for options changes
watch(options, () => {
  if (visible.value) {
    nextTick(() => refreshLegend());
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
  top: 10px;
  left: 10px;
  z-index: 1000;
}

.map-legend__inner {
  padding: 10px;
  background-color: rgba(0, 0, 0, 0.5);
  border-radius: 15px;
}

.legend-title {
  font-weight: bold;
  margin-bottom: 5px;
  font-size: 0.9rem;
  margin-left: 10px;
  color: #fff;
}

:deep(.x-axis line),
:deep(.x-axis path) {
  stroke: #fff;
}

:deep(.tick text) {
  font-size: 0.85rem;
  fill: #fff;
}
</style>
