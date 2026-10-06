<template>
  <div class="histogram-chart" ref="containerRef">
    <!-- Header -->
    <div class="histogram-chart__header">
      <h3 class="histogram-chart__title">{{ title }}</h3>
    </div>

    <!-- Chart - D3 manages the bars/labels for transitions -->
    <div v-if="hasData" class="histogram-chart__body">
      <div ref="chartWrapperRef" class="histogram-chart__wrapper">
        <svg
          ref="svgRef"
          :width="chartWidth"
          :height="computedHeight"
          class="histogram-chart__svg"
          aria-hidden="true"
          focusable="false"
        >
          <g
            ref="chartGroupRef"
            :transform="`translate(${margin.left}, ${margin.top})`"
          >
            <!-- D3 will render bars and labels here -->
          </g>
        </svg>
      </div>
    </div>
    <div v-else class="histogram-chart__empty">No data available</div>

    <!-- Accessible table (screen reader only) -->
    <table class="sr-only" role="table" :aria-label="accessibleLabel">
      <caption>
        {{
          accessibleLabel
        }}
      </caption>
      <thead>
        <tr>
          <th scope="col">Category</th>
          <th scope="col">Count</th>
          <th scope="col">Percentage</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in chartData" :key="`table-${item.category}`">
          <td>{{ item.fullLabel }}</td>
          <td>{{ item.count }}</td>
          <td>{{ item.percentLabel }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
/**
 * HistogramChart Component
 *
 * Horizontal bar chart showing distribution of shooting data by category.
 * Uses D3 for data binding and transitions, with smooth animations on filter changes.
 *
 * @component
 */

import { computed, ref, onMounted, onUnmounted, watch } from "vue";
import { rollup } from "d3-array";
import { scaleBand, scaleLinear } from "d3-scale";
import { select } from "d3-selection";
import { format } from "d3-format";
import "d3-transition";
import type { ShootingRow } from "@/shared/types/shootings";

// Types
interface ChartDataItem {
  category: string;
  label: string;
  fullLabel: string;
  count: number;
  percent: number;
  percentLabel: string;
}

interface Props {
  /** Array of filtered records to visualize */
  rows: ShootingRow[];
  /** Property key to group by */
  accessor: string;
  /** Chart title */
  title: string;
  /** Bar color (hex) */
  color: string;
  /** Ordered category values */
  categories: (string | number | boolean | null)[];
  /** Display labels for categories */
  aliases?: Record<string, string>;
  /** Short labels for mobile */
  shortAliases?: Record<string, string>;
  /** Chart height in pixels (ignored, auto-calculated) */
  height?: number;
  /** Y-axis label width */
  labelWidth?: number;
  /** Y-axis label width on mobile */
  responsiveLabelWidth?: number;
}

const props = withDefaults(defineProps<Props>(), {
  aliases: () => ({}),
  shortAliases: () => ({}),
  height: 200,
  labelWidth: 180,
  responsiveLabelWidth: 100,
});

// Refs
const containerRef = ref<HTMLElement | null>(null);
const chartWrapperRef = ref<HTMLElement | null>(null);
const chartGroupRef = ref<SVGGElement | null>(null);
const containerWidth = ref(400);
const chartWidth = ref(400);
const isMobile = ref(false);

// Check if user prefers reduced motion (accessibility)
const prefersReducedMotion = ref(false);

// Resize observer for responsive width
let resizeObserver: ResizeObserver | null = null;

onMounted(() => {
  // Check reduced motion preference
  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  prefersReducedMotion.value = motionQuery.matches;
  motionQuery.addEventListener("change", (e) => {
    prefersReducedMotion.value = e.matches;
  });

  if (containerRef.value) {
    resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        containerWidth.value = entry.contentRect.width;
        isMobile.value = entry.contentRect.width < 500;
      }
    });
    resizeObserver.observe(containerRef.value);
    // Initial measurement
    containerWidth.value = containerRef.value.clientWidth || 400;
    isMobile.value = containerWidth.value < 500;
  }

  // Observe the wrapper for actual chart width (respects max-width)
  if (chartWrapperRef.value) {
    const wrapperObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        chartWidth.value = entry.contentRect.width;
      }
    });
    wrapperObserver.observe(chartWrapperRef.value);
    chartWidth.value = chartWrapperRef.value.clientWidth || 400;
  }
});

onUnmounted(() => {
  resizeObserver?.disconnect();
});

// Format helpers
const formatCount = format(",");
const formatPercent = (p: number) => `${(p * 100).toFixed(0)}%`;

// Computed values
const hasData = computed(() => props.rows.length > 0);
const accessibleLabel = computed(() => `${props.title} distribution breakdown`);

// Chart dimensions
const barHeight = 40;
const barPadding = 0.25;

const margin = computed(() => ({
  top: 8,
  right: isMobile.value ? 110 : 150,
  bottom: 4,
  left: isMobile.value ? props.responsiveLabelWidth : props.labelWidth,
}));

const innerWidth = computed(() =>
  Math.max(0, chartWidth.value - margin.value.left - margin.value.right)
);

const computedHeight = computed(() => {
  const numBars = props.categories.length;
  return Math.max(
    numBars * barHeight + margin.value.top + margin.value.bottom,
    80
  );
});

const innerHeight = computed(
  () => computedHeight.value - margin.value.top - margin.value.bottom
);

/**
 * Group features by accessor and build chart data.
 */
const chartData = computed<ChartDataItem[]>(() => {
  if (!props.rows.length) return [];

  // Group by accessor value
  const grouped = rollup(
    props.rows,
    (v: ShootingRow[]) => v.length,
    (d: ShootingRow) => {
      const value = d[props.accessor as keyof ShootingRow];
      return props.accessor === "has_court_case" && typeof value !== "boolean"
        ? null
        : value;
    }
  );

  const total = props.rows.length;

  return props.categories.map((cat: string | number | boolean | null) => {
    const key = String(cat);
    const count = grouped.get(cat) ?? 0;
    const percent = total > 0 ? count / total : 0;

    return {
      category: key,
      label: isMobile.value
        ? props.shortAliases[key] ?? props.aliases[key] ?? key
        : props.aliases[key] ?? key,
      fullLabel: props.aliases[key] ?? key,
      count,
      percent,
      percentLabel: formatPercent(percent),
    };
  });
});

// D3 Scales
const xScale = computed(() =>
  scaleLinear()
    .domain([
      0,
      Math.max(...chartData.value.map((d: ChartDataItem) => d.count), 1),
    ])
    .range([0, innerWidth.value])
);

const yScale = computed(() =>
  scaleBand<string>()
    .domain(chartData.value.map((d: ChartDataItem) => d.category))
    .range([0, innerHeight.value])
    .padding(barPadding)
);

// Animation duration - respects prefers-reduced-motion
const transitionDuration = computed(() =>
  prefersReducedMotion.value ? 0 : 400
);

/**
 * Render chart with D3 transitions.
 * Uses enter/update/exit pattern for smooth animations.
 * Animations are disabled if user prefers reduced motion.
 */
function renderChart() {
  if (!chartGroupRef.value || !chartData.value.length) return;

  const g = select(chartGroupRef.value);
  const data = chartData.value;
  const bandWidth = yScale.value.bandwidth();
  const t = transitionDuration.value;

  // --- BARS ---
  const bars = g
    .selectAll<SVGRectElement, ChartDataItem>(".histogram-chart__bar")
    .data(data, (d: ChartDataItem) => d.category);

  // Enter
  (
    bars
      .enter()
      .append("rect")
      .attr("class", "histogram-chart__bar")
      .attr("x", 0)
      .attr("y", (d: ChartDataItem) => yScale.value(d.category) ?? 0)
      .attr("height", bandWidth)
      .attr("rx", 3)
      .attr("fill", props.color)
      .attr("width", 0) as any
  )
    .transition()
    .duration(t)
    .attr("width", (d: ChartDataItem) => Math.max(0, xScale.value(d.count)));

  // Update
  (bars as any)
    .transition()
    .duration(t)
    .attr("y", (d: ChartDataItem) => yScale.value(d.category) ?? 0)
    .attr("height", bandWidth)
    .attr("width", (d: ChartDataItem) => Math.max(0, xScale.value(d.count)));

  // Exit
  (bars.exit() as any).transition().duration(t).attr("width", 0).remove();

  // --- Y-AXIS LABELS ---
  const yLabels = g
    .selectAll<SVGTextElement, ChartDataItem>(".histogram-chart__axis-label")
    .data(data, (d: ChartDataItem) => d.category);

  // Enter
  yLabels
    .enter()
    .append("text")
    .attr("class", "histogram-chart__axis-label")
    .attr("x", -12)
    .attr(
      "y",
      (d: ChartDataItem) => (yScale.value(d.category) ?? 0) + bandWidth / 2
    )
    .attr("dy", "0.35em")
    .attr("text-anchor", "end")
    .attr("fill", "#fff")
    .attr("font-size", isMobile.value ? "17px" : "18px")
    .attr("font-weight", "500")
    .text((d: ChartDataItem) => d.label);

  // Update
  (yLabels as any)
    .transition()
    .duration(t)
    .attr(
      "y",
      (d: ChartDataItem) => (yScale.value(d.category) ?? 0) + bandWidth / 2
    );

  yLabels.text((d: ChartDataItem) => d.label);

  // Exit
  (yLabels.exit() as any).transition().duration(t).attr("opacity", 0).remove();

  // --- DATA LABELS ---
  const dataLabels = g
    .selectAll<SVGTextElement, ChartDataItem>(".histogram-chart__data-label")
    .data(data, (d: ChartDataItem) => d.category);

  // Enter
  const enterLabels = dataLabels
    .enter()
    .append("text")
    .attr("class", "histogram-chart__data-label")
    .attr(
      "y",
      (d: ChartDataItem) => (yScale.value(d.category) ?? 0) + bandWidth / 2
    )
    .attr("dy", "0.35em")
    .attr("x", (d: ChartDataItem) => xScale.value(d.count) + 8)
    .attr("fill", "#fff")
    .attr("font-size", isMobile.value ? "17px" : "18px")
    .attr("font-weight", "500");

  enterLabels
    .append("tspan")
    .attr("class", "histogram-chart__count")
    .text((d: ChartDataItem) => formatCount(d.count));

  enterLabels
    .append("tspan")
    .attr("class", "histogram-chart__percentage")
    .attr("fill", "rgba(255, 255, 255, 0.7)")
    .attr("font-size", isMobile.value ? "15px" : "16px")
    .attr("font-weight", "400")
    .text((d: ChartDataItem) => ` (${d.percentLabel})`);

  // Update - animate x position
  (dataLabels as any)
    .transition()
    .duration(t)
    .attr(
      "y",
      (d: ChartDataItem) => (yScale.value(d.category) ?? 0) + bandWidth / 2
    )
    .attr("x", (d: ChartDataItem) => xScale.value(d.count) + 8);

  // Update tspans text content
  dataLabels
    .select(".histogram-chart__count")
    .text((d: unknown) => formatCount((d as ChartDataItem).count));
  dataLabels
    .select(".histogram-chart__percentage")
    .text((d: unknown) => ` (${(d as ChartDataItem).percentLabel})`);

  // Exit
  (dataLabels.exit() as any)
    .transition()
    .duration(t)
    .attr("opacity", 0)
    .remove();
}

// Watch for data changes and re-render with transitions
watch(
  [chartData, xScale, yScale],
  () => {
    renderChart();
  },
  { deep: true }
);

// Initial render after mount
onMounted(() => {
  // Need to wait a tick for refs to be ready
  setTimeout(renderChart, 0);
});
</script>

<style scoped>
.histogram-chart {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-width: 0;
  background: rgba(0, 0, 0, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  padding: 24px 20px 28px;
}

.histogram-chart__header {
  margin-bottom: 20px;
}

.histogram-chart__title {
  font-size: 1.35rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.95);
  margin: 0;
  text-align: center;
  font-family: inherit;
  letter-spacing: 0.01em;
}

.histogram-chart__body {
  flex: 1;
  display: flex;
  justify-content: center;
}

.histogram-chart__wrapper {
  width: 100%;
  max-width: 750px;
}

.histogram-chart__svg {
  display: block;
  max-width: 100%;
  height: auto;
}

.histogram-chart__bar {
  opacity: 0.9;
  rx: 3;
  transition: opacity 0.15s ease;
}

.histogram-chart__bar:hover {
  opacity: 1;
}

.histogram-chart__axis-label {
  fill: #ffffff;
  font-size: 17px;
  font-weight: 500;
}

.histogram-chart__data-label {
  fill: rgba(255, 255, 255, 0.95);
  font-size: 17px;
  font-weight: 600;
}

.histogram-chart__percentage {
  fill: rgba(255, 255, 255, 0.6);
  font-size: 15px;
  font-weight: 400;
}

.histogram-chart__empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100px;
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.875rem;
}

/* Screen reader only */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 768px) {
  .histogram-chart__title {
    font-size: 1.3rem;
    margin-top: 16px;
  }
}
</style>
