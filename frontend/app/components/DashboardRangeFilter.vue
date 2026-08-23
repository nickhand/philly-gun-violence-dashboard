<script setup lang="ts">
import { computed, ref } from "vue";

import CivicCheckboxField from "../../layers/civic-ui/app/components/CivicCheckboxField.vue";
import type {
  NumericRange,
  ShootingHistogramBin,
} from "~/utils/shootingFilters";

const props = withDefaults(
  defineProps<{
    bins: ShootingHistogramBin[];
    defaultRange: NumericRange;
    excludeMissing?: boolean;
    format: "age" | "date" | "time";
    id: string;
    includeYear?: boolean;
    label: string;
    range: NumericRange;
    resettable?: boolean;
    showExcludeMissing?: boolean;
    step: number;
  }>(),
  {
    excludeMissing: false,
    includeYear: false,
    resettable: true,
    showExcludeMissing: false,
  },
);

const emit = defineEmits<{
  change: [value: NumericRange];
  reset: [];
  "update:excludeMissing": [value: boolean];
  "update:range": [value: NumericRange];
}>();

const lowerInput = ref<HTMLInputElement | null>(null);
const upperInput = ref<HTMLInputElement | null>(null);

const maximumBinCount = computed(() =>
  Math.max(...props.bins.map((item) => item.length), 1),
);

const isModified = computed(
  () =>
    props.range[0] !== props.defaultRange[0] ||
    props.range[1] !== props.defaultRange[1] ||
    Boolean(props.excludeMissing),
);

const histogramLabel = computed(
  () =>
    `${props.label} distribution across ${props.bins.length} bins. Bars inside the selected range are highlighted.`,
);

const selectedRangeFraction = computed(() => {
  const fullRange = props.defaultRange[1] - props.defaultRange[0];
  if (fullRange <= 0) return 1;
  return (props.range[1] - props.range[0]) / fullRange;
});

const stackCompactLabels = computed(() => selectedRangeFraction.value < 0.35);

function rangePosition(value: number): number {
  const fullRange = props.defaultRange[1] - props.defaultRange[0];
  if (fullRange <= 0) return 0;
  return Math.max(
    0,
    Math.min(100, ((value - props.defaultRange[0]) / fullRange) * 100),
  );
}

const lowerPosition = computed(() => rangePosition(props.range[0]));
const upperPosition = computed(() => rangePosition(props.range[1]));
const selectedTrackStyle = computed(() => ({
  left: `${lowerPosition.value}%`,
  width: `${Math.max(0, upperPosition.value - lowerPosition.value)}%`,
}));

function compactLabelStyle(position: number): Record<string, string> {
  return { "--range-position": `${position}%` };
}

function histogramLimitStyle(position: number): Record<string, string> {
  const inset = (position / 100) * 0.5;
  return {
    left: `calc(0.25rem + ${position}% - ${inset}rem)`,
  };
}

function formatValue(value: number): string {
  if (props.format === "age") return String(Math.round(value));
  if (props.format === "date") {
    return new Intl.DateTimeFormat("en-US", {
      day: "numeric",
      month: "short",
      timeZone: "UTC",
      ...(props.includeYear ? { year: "numeric" as const } : {}),
    }).format(new Date(value));
  }

  const totalMinutes = Math.floor(value / 60_000);
  const hours = Math.floor(totalMinutes / 60) % 24;
  const minutes = totalMinutes % 60;
  const hour = hours % 12 || 12;
  return `${hour}:${String(minutes).padStart(2, "0")} ${hours >= 12 ? "PM" : "AM"}`;
}

function updateLower(event: Event): void {
  const value = Number((event.target as HTMLInputElement).value);
  emit("update:range", [Math.min(value, props.range[1]), props.range[1]]);
}

function updateUpper(event: Event): void {
  const value = Number((event.target as HTMLInputElement).value);
  emit("update:range", [props.range[0], Math.max(value, props.range[0])]);
}

function updateExcludeMissing(value: boolean): void {
  emit("update:excludeMissing", value);
}

function commitRange(): void {
  emit("change", [
    Number(lowerInput.value?.value ?? props.range[0]),
    Number(upperInput.value?.value ?? props.range[1]),
  ]);
}

function barHeight(item: ShootingHistogramBin): string {
  return `${(item.length / maximumBinCount.value) * 100}%`;
}

function isSelected(item: ShootingHistogramBin): boolean {
  const midpoint = (item.x0 + item.x1) / 2;
  return midpoint >= props.range[0] && midpoint <= props.range[1];
}
</script>

<template>
  <fieldset
    class="usa-fieldset civic-dashboard-range-filter civic-dashboard-range-filter--compact"
  >
    <legend class="usa-legend">{{ label }}</legend>

    <div
      class="civic-dashboard-range-filter__histogram"
      role="img"
      :aria-label="histogramLabel"
    >
      <span
        v-for="(item, index) in bins"
        :key="`${item.x0}-${item.x1}-${index}`"
        aria-hidden="true"
        :class="{
          'civic-dashboard-range-filter__bar--selected': isSelected(item),
        }"
        :style="{ height: barHeight(item) }"
      ></span>
      <span
        aria-hidden="true"
        class="civic-dashboard-range-filter__limit"
        :style="histogramLimitStyle(lowerPosition)"
      ></span>
      <span
        aria-hidden="true"
        class="civic-dashboard-range-filter__limit"
        :style="histogramLimitStyle(upperPosition)"
      ></span>
    </div>

    <div
      class="civic-dashboard-range-filter__dual-range"
      :class="{
        'civic-dashboard-range-filter__dual-range--stacked': stackCompactLabels,
      }"
    >
      <span
        aria-hidden="true"
        class="civic-dashboard-range-filter__thumb-label civic-dashboard-range-filter__thumb-label--lower"
        :style="compactLabelStyle(lowerPosition)"
      >
        {{ formatValue(range[0]) }}
      </span>
      <span
        aria-hidden="true"
        class="civic-dashboard-range-filter__thumb-label civic-dashboard-range-filter__thumb-label--upper"
        :style="compactLabelStyle(upperPosition)"
      >
        {{ formatValue(range[1]) }}
      </span>

      <div class="civic-dashboard-range-filter__dual-track" aria-hidden="true">
        <span
          class="civic-dashboard-range-filter__dual-track-selection"
          :style="selectedTrackStyle"
        ></span>
      </div>

      <label
        class="civic-dashboard-range-filter__sr-label"
        :for="`${id}-lower`"
      >
        {{ label }} start
      </label>
      <input
        :id="`${id}-lower`"
        ref="lowerInput"
        class="civic-dashboard-range-filter__dual-input civic-dashboard-range-filter__dual-input--lower"
        type="range"
        :min="defaultRange[0]"
        :max="defaultRange[1]"
        :step="step"
        :value="range[0]"
        :aria-valuetext="formatValue(range[0])"
        @change="commitRange"
        @input="updateLower"
      />

      <label
        class="civic-dashboard-range-filter__sr-label"
        :for="`${id}-upper`"
      >
        {{ label }} end
      </label>
      <input
        :id="`${id}-upper`"
        ref="upperInput"
        class="civic-dashboard-range-filter__dual-input civic-dashboard-range-filter__dual-input--upper"
        type="range"
        :min="defaultRange[0]"
        :max="defaultRange[1]"
        :step="step"
        :value="range[1]"
        :aria-valuetext="formatValue(range[1])"
        @change="commitRange"
        @input="updateUpper"
      />
    </div>

    <CivicCheckboxField
      v-if="showExcludeMissing"
      :id="`${id}-exclude-missing`"
      label="Exclude unknown values"
      :model-value="excludeMissing"
      tone="inverse"
      @update:model-value="updateExcludeMissing"
    />

    <button
      v-if="resettable && isModified"
      class="civic-dashboard-range-filter__reset"
      type="button"
      :aria-label="`Reset ${label} filter`"
      @click="emit('reset')"
    >
      Reset
    </button>
  </fieldset>
</template>

<style scoped>
.civic-dashboard-range-filter--compact {
  padding: 0;
  border: 0;
}

.civic-dashboard-range-filter--compact .usa-legend {
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

.civic-dashboard-range-filter__dual-range {
  position: relative;
  height: 3.35rem;
  margin-top: 0.85rem;
}

.civic-dashboard-range-filter__dual-range--stacked {
  height: 5.15rem;
}

.civic-dashboard-range-filter__dual-track {
  position: absolute;
  z-index: 1;
  top: 2rem;
  right: 0;
  left: 0;
  height: 0.35rem;
  overflow: hidden;
  border-radius: 999px;
  background: #778188;
}

.civic-dashboard-range-filter__dual-track-selection {
  position: absolute;
  top: 0;
  bottom: 0;
  background: #7ab5e5;
}

.civic-dashboard-range-filter__dual-input {
  position: absolute;
  z-index: 3;
  top: 1.4rem;
  left: -0.55rem;
  width: calc(100% + 1.1rem);
  height: 1.55rem;
  padding: 0;
  margin: 0;
  appearance: none;
  border: 0;
  outline-offset: 2px;
  background: transparent;
  pointer-events: none;
}

.civic-dashboard-range-filter__dual-input--upper {
  z-index: 4;
}

.civic-dashboard-range-filter__dual-input::-webkit-slider-runnable-track {
  height: 0.35rem;
  border: 0;
  background: transparent;
}

.civic-dashboard-range-filter__dual-input::-moz-range-track {
  height: 0.35rem;
  border: 0;
  background: transparent;
}

.civic-dashboard-range-filter__dual-input::-webkit-slider-thumb {
  width: 1.1rem;
  height: 1.1rem;
  margin-top: -0.375rem;
  appearance: none;
  border: 2px solid #ffffff;
  border-radius: 50%;
  background: #7ab5e5;
  cursor: grab;
  pointer-events: auto;
}

.civic-dashboard-range-filter__dual-input::-moz-range-thumb {
  width: 1.1rem;
  height: 1.1rem;
  border: 2px solid #ffffff;
  border-radius: 50%;
  background: #7ab5e5;
  cursor: grab;
  pointer-events: auto;
}

.civic-dashboard-range-filter__dual-input:active::-webkit-slider-thumb {
  cursor: grabbing;
}

.civic-dashboard-range-filter__dual-input:active::-moz-range-thumb {
  cursor: grabbing;
}

.civic-dashboard-range-filter__thumb-label {
  position: absolute;
  z-index: 5;
  top: 0;
  left: var(--range-position);
  min-width: max-content;
  padding: 0.2rem 0.4rem;
  transform: translateX(-50%);
  border-radius: 3px;
  color: #172126;
  background: #7ab5e5;
  font-size: 0.75rem;
  font-variant-numeric: tabular-nums;
  font-weight: 400;
  line-height: 1.2;
  white-space: nowrap;
}

.civic-dashboard-range-filter__histogram {
  position: relative;
}

.civic-dashboard-range-filter__histogram
  .civic-dashboard-range-filter__limit {
  position: absolute;
  z-index: 2;
  top: 0;
  bottom: 0;
  width: 2px;
  min-width: 0;
  flex: none;
  transform: translateX(-1px);
  background: #ffffff;
}

.civic-dashboard-range-filter__thumb-label::after {
  position: absolute;
  top: 100%;
  left: 50%;
  width: 0;
  height: 0;
  transform: translateX(-50%);
  border-top: 0.3rem solid #7ab5e5;
  border-right: 0.3rem solid transparent;
  border-left: 0.3rem solid transparent;
  content: "";
}

.civic-dashboard-range-filter__dual-range--stacked
  .civic-dashboard-range-filter__thumb-label--upper {
  top: 3.05rem;
}

.civic-dashboard-range-filter__dual-range--stacked
  .civic-dashboard-range-filter__thumb-label--upper::after {
  top: auto;
  bottom: 100%;
  border-top: 0;
  border-right: 0.3rem solid transparent;
  border-bottom: 0.3rem solid #7ab5e5;
  border-left: 0.3rem solid transparent;
}

.civic-dashboard-range-filter__sr-label {
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
</style>
