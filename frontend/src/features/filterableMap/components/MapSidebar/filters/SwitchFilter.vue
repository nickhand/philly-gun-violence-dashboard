<template>
  <FilterPanel hide-actions class="switch-filter">
    <template #title>
      <v-switch
        :model-value="modelValue"
        :label="label"
        color="#7ab5e5"
        hide-details
        density="compact"
        @update:model-value="$emit('update:modelValue', $event)"
        @click.stop
      >
        <template #label>
          <span class="ms-2">{{ label }}</span>
        </template>
      </v-switch>
    </template>
  </FilterPanel>
</template>

<script setup lang="ts">
/**
 * SwitchFilter Component
 *
 * A toggle switch filter displayed in an expansion panel.
 * Used for boolean filters like "Fatal shootings only".
 *
 * @component
 */

import FilterPanel from "./FilterPanel.vue";

defineProps<{
  /** Current switch value */
  modelValue: boolean;
  /** Filter label */
  label: string;
}>();

defineEmits<{
  /** Emitted when switch is toggled */
  "update:modelValue": [value: boolean | null];
}>();
</script>

<style scoped>
.switch-filter {
  border-top: none !important;
  border-bottom: none !important;
}

.switch-filter:last-of-type {
  margin-bottom: 8px !important;
}

.switch-filter :deep(.v-expansion-panel-title) {
  min-height: 36px !important;
  padding-top: 4px !important;
  padding-bottom: 4px !important;
}

/* Switch label color (default) */
.switch-filter :deep(.v-label) {
  color: #fff !important;
  opacity: 1 !important;
}

/* Switch track color when off */
.switch-filter :deep(.v-switch__track) {
  background-color: rgba(255, 255, 255, 0.3) !important;
}

/* Switch track color when on */
.switch-filter :deep(.v-switch--inset .v-switch__track) {
  opacity: 1 !important;
}

/* Set the color of the thumb in off mode */
.switch-filter
  :deep(.v-selection-control:not(.v-selection-control--dirty))
  .v-switch__thumb {
  background-color: #9e9e9e;
}
</style>
