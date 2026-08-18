<script setup lang="ts">
import { computed } from "vue";

import CivicCheckboxField from "../../layers/civic-ui/app/components/CivicCheckboxField.vue";

export interface DashboardCheckboxFilterItem {
  label: string;
  value: number | string;
}

const props = withDefaults(
  defineProps<{
    columns?: 1 | 2;
    defaultValues: Array<number | string>;
    disabled?: boolean;
    id: string;
    items: DashboardCheckboxFilterItem[];
    label: string;
    onlyDisabled?: boolean | null;
    resettable?: boolean;
    selectedValues: Array<number | string>;
  }>(),
  {
    columns: 1,
    disabled: false,
    onlyDisabled: null,
    resettable: true,
  },
);

const emit = defineEmits<{
  reset: [];
  "select-only": [value: number | string];
  "update:selectedValues": [value: Array<number | string>];
}>();

const isModified = computed(
  () =>
    props.selectedValues.length !== props.defaultValues.length ||
    props.selectedValues.some(
      (value, index) => value !== props.defaultValues[index],
    ),
);

function update(itemValue: number | string, checked: boolean): void {
  const next = new Set(props.selectedValues);
  if (checked) next.add(itemValue);
  else next.delete(itemValue);

  emit(
    "update:selectedValues",
    props.items.map((item) => item.value).filter((value) => next.has(value)),
  );
}

function selectOnly(itemValue: number | string): void {
  emit("select-only", itemValue);
}
</script>

<template>
  <fieldset
    class="usa-fieldset civic-dashboard-checkbox-filter civic-dashboard-checkbox-filter--compact"
    :class="{
      'civic-dashboard-checkbox-filter--two-columns': columns === 2,
    }"
  >
    <legend class="usa-legend">{{ label }}</legend>
    <ul class="civic-dashboard-checkbox-filter__list">
      <li v-for="(item, index) in items" :key="item.value">
        <CivicCheckboxField
          :id="`${id}-${index}`"
          :disabled="disabled"
          :label="item.label"
          :model-value="selectedValues.includes(item.value)"
          tone="inverse"
          @update:model-value="update(item.value, $event)"
        />
        <button
          class="civic-dashboard-checkbox-filter__only"
          type="button"
          :disabled="onlyDisabled ?? disabled"
          :aria-label="`Select only ${item.label} for ${label}`"
          @click="selectOnly(item.value)"
        >
          only
        </button>
      </li>
    </ul>
    <button
      v-if="resettable && isModified"
      class="civic-dashboard-filter-reset"
      type="button"
      :disabled="disabled"
      :aria-label="`Reset ${label} filter`"
      @click="emit('reset')"
    >
      Reset
    </button>
  </fieldset>
</template>

<style scoped>
.civic-dashboard-checkbox-filter--compact {
  padding: 0;
  border: 0;
}

.civic-dashboard-checkbox-filter--compact .usa-legend {
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

.civic-dashboard-checkbox-filter--compact
  .civic-dashboard-checkbox-filter__list {
  gap: 0.25rem;
}
</style>
