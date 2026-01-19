<template>
  <div class="checkbox-grid">
    <v-hover
      v-for="item in normalizedItems"
      :key="String(item.value)"
      v-slot="{ isHovering, props: hoverProps }"
    >
      <div v-bind="hoverProps" class="checkbox-item" :style="getItemStyle()">
        <v-checkbox
          :model-value="selectedValues.includes(item.value)"
          :disabled="disabled"
          color="#7ab5e5"
          hide-details
          density="compact"
          @click.capture="handleCheckboxClick"
          @update:model-value="handleChange(item.value, $event)"
        >
          <template #label>
            <div class="checkbox-label">
              {{ item.text }}
              <span
                v-if="isHovering && !disabled && showOnly"
                class="only-link"
                @mousedown.stop.prevent="handleOnlyClick(item.value)"
              >
                only
              </span>
            </div>
          </template>
        </v-checkbox>
      </div>
    </v-hover>
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

import { ref, computed } from "vue";

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

/** Flag to track if "only" was clicked (prevents checkbox toggle) */
const onlyClicked = ref(false);

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

/** Intercept checkbox clicks - block if "only" was just clicked */
function handleCheckboxClick(event: Event): void {
  if (onlyClicked.value) {
    event.stopPropagation();
    event.preventDefault();
    onlyClicked.value = false;
  }
}

/** Handle checkbox toggle */
function handleChange(value: any, checked: boolean | null): void {
  emit("change", value, checked ?? false);
}

/** Handle "only" link click - select just this value */
function handleOnlyClick(value: any): void {
  onlyClicked.value = true;
  emit("only", value);
}
</script>

<style scoped>
.checkbox-grid {
  display: flex;
  flex-wrap: wrap;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.only-link {
  color: #7ab5e5;
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
}

.only-link:hover {
  text-decoration: underline;
}
</style>
