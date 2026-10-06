<template>
  <FilterPanel :label="label" :show-reset="isModified" @reset="$emit('reset')">
    <CheckboxGroup
      :items="categories"
      :selected-values="selectedValues"
      :ncol="ncol"
      @change="(value, checked) => $emit('change', value, checked)"
      @only="(value) => $emit('only', value)"
    />
  </FilterPanel>
</template>

<script setup lang="ts">
/**
 * CheckboxFilter Component
 *
 * A checkbox group filter displayed in an expansion panel.
 * Uses shared CheckboxGroup component for the checkbox rendering.
 *
 * Features:
 * - Hover to show "only" link that selects just that item
 * - Reset link when modified from defaults
 *
 * @component
 */

import { computed } from "vue";
import FilterPanel from "./FilterPanel.vue";
import CheckboxGroup from "./CheckboxGroup.vue";

/** Category option for checkbox */
interface Category {
  value: any;
  text: string;
}

const props = defineProps<{
  /** Filter label */
  label: string;
  /** Available category options */
  categories: Category[];
  /** Currently selected values */
  selectedValues: any[];
  /** Default values (for reset comparison) */
  defaultValues: any[];
  /** Number of columns for layout (1 or 2) */
  ncol?: number;
}>();

defineEmits<{
  /** Emitted when a checkbox is toggled */
  change: [value: any, checked: boolean];
  /** Emitted when "only" is clicked - sets selection to just this value */
  only: [value: any];
  /** Emitted when reset link is clicked */
  reset: [];
}>();

/** Check if filter has been modified from defaults */
const isModified = computed(() => {
  if (props.selectedValues.length !== props.defaultValues.length) return true;
  return !props.defaultValues.every((v) => props.selectedValues.includes(v));
});
</script>
