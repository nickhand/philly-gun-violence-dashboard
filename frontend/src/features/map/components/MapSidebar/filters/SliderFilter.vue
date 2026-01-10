<template>
  <FilterPanel :label="label" :show-reset="isModified" @reset="$emit('reset')">
    <div class="slider-container">
      <!-- Histogram chart (shown above slider when enabled) -->
      <SliderHistogramChart
        v-if="showHistogram && histogramData && histogramData.length > 0"
        :bins="histogramData"
        :lower="modelValue[0]"
        :upper="modelValue[1]"
        :min="min"
        :max="max"
        :height="60"
      />

      <!-- Spacer between histogram and slider to prevent label overlap -->
      <div
        v-if="showHistogram && histogramData && histogramData.length > 0"
        class="histogram-slider-spacer"
      />

      <v-range-slider
        :model-value="modelValue"
        :min="min"
        :max="max"
        :step="step"
        thumb-label="always"
        color="#7ab5e5"
        track-color="grey"
        strict
        :class="{ 'labels-stacked': shouldStackLabels }"
        @update:model-value="$emit('update:modelValue', $event)"
      >
        <!-- Custom thumb label formatting -->
        <template #thumb-label="{ modelValue: thumbValue }">
          <span class="thumb-label-text">{{
            formatThumbValue(thumbValue)
          }}</span>
        </template>
      </v-range-slider>

      <v-switch
        v-if="showExcludeMissing"
        :model-value="excludeMissing"
        label="Exclude unknown values"
        color="#7ab5e5"
        hide-details
        density="compact"
        @update:model-value="$emit('update:excludeMissing', $event)"
      />
    </div>
  </FilterPanel>
</template>

<script setup lang="ts">
/**
 * SliderFilter Component
 *
 * A range slider filter displayed in an expansion panel.
 * Used for numeric range filters like Time of Day, Date, Age.
 * Optionally displays a histogram chart showing data distribution.
 * Supports custom tooltip formatting for displaying human-readable values.
 *
 * @component
 */

import { computed } from "vue";
import FilterPanel from "./FilterPanel.vue";
import SliderHistogramChart from "./SliderHistogramChart.vue";
import type { HistogramBin } from "../../types";

const props = defineProps<{
  /** Filter label */
  label: string;
  /** Current range value [min, max] */
  modelValue: [number, number];
  /** Default range value (for reset comparison) */
  defaultValue: [number, number];
  /** Minimum allowed value */
  min: number;
  /** Maximum allowed value */
  max: number;
  /** Step increment */
  step?: number;
  /** Whether to show exclude missing switch */
  showExcludeMissing?: boolean;
  /** Current exclude missing value */
  excludeMissing?: boolean;
  /** Whether to show histogram chart */
  showHistogram?: boolean;
  /** Histogram bin data */
  histogramData?: HistogramBin[];
  /** Custom formatter for thumb label display (e.g., convert ms to time string) */
  tooltipFormatter?: (value: number) => string;
}>();

defineEmits<{
  /** Emitted when slider value changes */
  "update:modelValue": [value: [number, number]];
  /** Emitted when exclude missing is toggled */
  "update:excludeMissing": [value: boolean | null];
  /** Emitted when reset link is clicked */
  reset: [];
}>();

/** Check if filter has been modified from defaults */
const isModified = computed(() => {
  return (
    props.modelValue[0] !== props.defaultValue[0] ||
    props.modelValue[1] !== props.defaultValue[1]
  );
});

/**
 * Determine if thumb labels should be stacked (one above, one below)
 * to prevent overlap when handles are close together.
 * Legacy behavior: stack when range is < 35% of total width.
 */
const shouldStackLabels = computed(() => {
  const totalRange = props.max - props.min;
  if (totalRange === 0) return false;
  const currentRange = props.modelValue[1] - props.modelValue[0];
  const fraction = currentRange / totalRange;
  return fraction < 0.35;
});

/** Format thumb value using custom formatter or default to raw value */
function formatThumbValue(value: number): string {
  if (props.tooltipFormatter) {
    return props.tooltipFormatter(value);
  }
  return String(value);
}
</script>

<style scoped>
.slider-container {
  padding: 16px 8px;
  padding-bottom: 8px;
}

/* Spacer between histogram and slider labels */
.histogram-slider-spacer {
  height: 28px;
}

.thumb-label-text {
  font-size: 0.75rem;
  white-space: nowrap;
}

/*
 * When labels need to be stacked to prevent overlap:
 * - First thumb label stays above (default position)
 * - Second thumb label moves below with caret pointing up
 */

/* Move second label below the thumb */
.labels-stacked
  :deep(.v-slider-thumb:last-of-type .v-slider-thumb__label-container) {
  top: auto;
  bottom: 0;
}

.labels-stacked :deep(.v-slider-thumb:last-of-type .v-slider-thumb__label) {
  bottom: auto;
  top: calc(var(--v-slider-thumb-size) / 2 + 4px);
}

/* Flip the wedge/caret to point upward */
.labels-stacked
  :deep(.v-slider-thumb:last-of-type .v-slider-thumb__label-wedge) {
  /* Change from pointing down to pointing up */
  clip-path: polygon(50% 0%, 0% 50%, 100% 50%);
  /* Move from bottom to top */
  bottom: auto;
  top: calc(-6px + 0.2px);
}
</style>
