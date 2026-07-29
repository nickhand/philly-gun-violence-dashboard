<template>
  <div class="checkbox-grid">
    <div
      v-for="item in normalizedItems"
      :key="String(item.value)"
      class="checkbox-item"
      :style="getItemStyle()"
    >
      <v-checkbox
        :model-value="selectedValues.includes(item.value)"
        :disabled="disabled"
        color="#7ab5e5"
        hide-details
        density="compact"
        @update:model-value="handleChange(item.value, $event)"
      >
        <template #label>
          <span class="checkbox-label">{{ item.text }}</span>
        </template>
      </v-checkbox>
      <button
        v-if="!disabled && showOnly"
        type="button"
        class="only-button"
        :aria-label="`Show only ${item.text}`"
        @click="emit('only', item.value)"
      >
        only
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * CheckboxGroup Component
 *
 * A reusable checkbox group for multi-select scenarios.
 * Used by both CheckboxFilter (in expansion panels) and MapLayersPanel.
 *
 * Features:
 * - Hover to show "only" link that selects just that item
 * - Supports simple strings or {value, text} objects
 * - Configurable column layout
 *
 * @component
 */

import { computed } from "vue";

/** Item can be either a simple string or an object with value/text */
type CheckboxItem = string | { value: any; text: string };

const props = withDefaults(
  defineProps<{
    /** Items to display as checkboxes */
    items: CheckboxItem[];
    /** Currently selected values */
    selectedValues: any[];
    /** Number of columns for layout (1 or 2) */
    ncol?: number;
    /** Whether all checkboxes are disabled */
    disabled?: boolean;
    /** Whether to show the "only" link on hover */
    showOnly?: boolean;
  }>(),
  {
    ncol: 2,
    disabled: false,
    showOnly: true,
  }
);

const emit = defineEmits<{
  /** Emitted when a checkbox is toggled */
  change: [value: any, checked: boolean];
  /** Emitted when "only" is clicked - sets selection to just this value */
  only: [value: any];
}>();

/** Normalize items to always have value/text structure */
const normalizedItems = computed(() =>
  props.items.map((item) =>
    typeof item === "string" ? { value: item, text: item } : item
  )
);

/** Get inline style for checkbox item based on ncol */
function getItemStyle(): Record<string, string> {
  const width = props.ncol === 1 ? "100%" : `${100 / props.ncol}%`;
  return { minWidth: width, width };
}

/** Handle checkbox toggle */
function handleChange(value: any, checked: boolean | null): void {
  emit("change", value, checked ?? false);
}
</script>

<style scoped>
.checkbox-grid {
  display: flex;
  flex-wrap: wrap;
}

.checkbox-item {
  display: flex;
  align-items: center;
}

.checkbox-item :deep(.v-checkbox) {
  flex: 1;
}

.checkbox-label {
  display: inline-block;
}

.only-button {
  color: #7ab5e5;
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
  padding: 0.4rem;
  margin-right: 0.25rem;
  background: transparent;
  border: 0;
  border-radius: 4px;
}

.checkbox-item:hover .only-button,
.checkbox-item:focus-within .only-button {
  opacity: 1;
  pointer-events: auto;
}

.only-button:hover {
  text-decoration: underline;
}
</style>
