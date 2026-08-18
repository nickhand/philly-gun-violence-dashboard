<script setup lang="ts">
import { useAttrs } from "vue";

defineOptions({ inheritAttrs: false });

type CivicCheckboxTone = "default" | "inverse";

const props = withDefaults(
  defineProps<{
    disabled?: boolean;
    id: string;
    label: string;
    modelValue: boolean;
    tone?: CivicCheckboxTone;
  }>(),
  { disabled: false, tone: "default" },
);

const emit = defineEmits<{
  "update:modelValue": [value: boolean];
}>();

const attrs = useAttrs();

function update(event: Event): void {
  if (props.disabled) return;
  emit(
    "update:modelValue",
    (event.currentTarget as HTMLInputElement).checked,
  );
}
</script>

<template>
  <div
    class="usa-checkbox civic-checkbox-field"
    :class="`civic-checkbox-field--${tone}`"
  >
    <input
      v-bind="attrs"
      :id="id"
      class="usa-checkbox__input civic-checkbox-field__input"
      type="checkbox"
      :checked="modelValue"
      :disabled="disabled"
      @change="update"
    />
    <label
      class="usa-checkbox__label civic-checkbox-field__label"
      :for="id"
    >
      {{ label }}
    </label>
  </div>
</template>

<style scoped>
.civic-checkbox-field {
  display: flex;
  min-height: 2.5rem;
  gap: 0;
  align-items: center;
}

.civic-checkbox-field__input {
  flex: 0 0 auto;
}

.civic-checkbox-field--inverse .civic-checkbox-field__input {
  width: 1.75rem;
  height: 1.75rem;
  margin: 0;
  appearance: none;
  border: 0;
  border-radius: 50%;
  background-color: transparent;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23ffffff' d='M19 3H5C3.89 3 3 3.89 3 5v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.11-.9-2-2-2Zm0 2v14H5V5h14Z'/%3E%3C/svg%3E");
  background-position: center;
  background-repeat: no-repeat;
  background-size: 1.5rem;
}

.civic-checkbox-field--inverse .civic-checkbox-field__input:checked {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%237ab5e5' d='m10 17-5-5 1.41-1.42L10 14.17l7.59-7.59L19 8M19 3H5C3.89 3 3 3.89 3 5v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.11-.9-2-2-2Z'/%3E%3C/svg%3E");
}

@media (forced-colors: active) {
  .civic-checkbox-field--inverse .civic-checkbox-field__input {
    appearance: auto;
    background-image: none;
  }
}
</style>
