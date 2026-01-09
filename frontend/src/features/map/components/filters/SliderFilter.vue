<template>
  <FilterPanel :label="label" :show-reset="isModified" @reset="$emit('reset')">
    <div class="slider-container">
      <v-range-slider
        :model-value="modelValue"
        :min="min"
        :max="max"
        :step="step"
        thumb-label="always"
        color="#7ab5e5"
        track-color="grey"
        @update:model-value="$emit('update:modelValue', $event)"
      />

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
 *
 * @component
 */

import { computed } from "vue";
import FilterPanel from "./FilterPanel.vue";

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
</script>

<style scoped>
.slider-container {
  padding: 16px 8px;
}
</style>
