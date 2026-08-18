<script setup lang="ts">
import { computed, ref, useAttrs } from "vue";

defineOptions({ inheritAttrs: false });

export interface CivicSelectOption {
  disabled?: boolean;
  label: string;
  value: string;
}

type CivicSelectTone = "default" | "inverse";

interface CivicSelectFieldBaseProps {
  disabled?: boolean;
  hint?: string;
  id: string;
  label: string;
  modelValue: string;
  name?: string;
  options: CivicSelectOption[];
}

type CivicSelectFieldProps = CivicSelectFieldBaseProps &
  (
    | {
        clearable?: false;
        floatingLabel?: false;
        tone?: CivicSelectTone;
      }
    | {
        clearable?: boolean;
        floatingLabel: true;
        tone: "inverse";
      }
  );

const props = withDefaults(
  defineProps<CivicSelectFieldProps>(),
  {
    clearable: false,
    disabled: false,
    floatingLabel: false,
    hint: undefined,
    name: undefined,
    tone: "default",
  },
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

const hintId = computed(() => `${props.id}-hint`);
const attrs = useAttrs();
const selectElement = ref<HTMLSelectElement | null>(null);
const isFloating = computed(
  () => props.floatingLabel === true && props.tone === "inverse",
);
const isClearable = computed(() => props.clearable === true && isFloating.value);
const describedBy = computed(() => {
  const callerDescription = attrs["aria-describedby"];
  const ids = [
    typeof callerDescription === "string" ? callerDescription.trim() : "",
    props.hint ? hintId.value : "",
  ].filter(Boolean);
  return ids.length > 0 ? ids.join(" ") : undefined;
});

function update(event: Event): void {
  if (props.disabled) return;
  emit(
    "update:modelValue",
    (event.currentTarget as HTMLSelectElement).value,
  );
}

function clear(): void {
  if (props.disabled || !isClearable.value) return;
  emit("update:modelValue", "");
  selectElement.value?.focus();
}
</script>

<template>
  <div
    class="civic-select-field"
    :class="[
      `civic-select-field--${tone}`,
      {
        'civic-select-field--clearable': isClearable,
        'civic-select-field--filled': modelValue !== '',
        'civic-select-field--floating': isFloating,
      },
    ]"
  >
    <div class="civic-select-field__input">
      <label class="usa-label" :for="id">
        {{ label }}
      </label>
      <select
        v-bind="$attrs"
        :id="id"
        ref="selectElement"
        class="usa-select civic-select-field__control"
        :name="name"
        :value="modelValue"
        :disabled="disabled"
        :aria-describedby="describedBy"
        @change="update"
      >
        <option
          v-for="option in options"
          :key="option.value"
          :value="option.value"
          :disabled="option.disabled"
        >
          {{ option.label }}
        </option>
      </select>
      <button
        v-if="isClearable && modelValue"
        class="civic-select-field__clear"
        type="button"
        :aria-label="`Clear ${label}`"
        :disabled="disabled"
        @click="clear"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24">
          <path
            d="M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20Zm3.59 5L12 10.59 8.41 7 7 8.41 10.59 12 7 15.59 8.41 17 12 13.41 15.59 17 17 15.59 13.41 12 17 8.41 15.59 7Z"
          />
        </svg>
      </button>
    </div>
    <p v-if="hint" :id="hintId" class="usa-hint">
      {{ hint }}
    </p>
  </div>
</template>

<style scoped>
.civic-select-field {
  min-width: 0;
}

.civic-select-field__input {
  position: relative;
}

.civic-select-field .usa-label {
  margin-top: 0;
  color: var(--civic-color-ink);
  font-weight: 400;
}

.civic-select-field__control {
  width: 100%;
  max-width: none;
}

.civic-select-field--clearable .civic-select-field__control {
  padding-right: 4rem;
}

.civic-select-field__clear {
  position: absolute;
  z-index: 2;
  top: 0;
  right: 1.75rem;
  bottom: 0;
  display: grid;
  width: 2rem;
  padding: 0;
  place-items: center;
  border: 0;
  color: inherit;
  background: transparent;
  cursor: pointer;
}

.civic-select-field__clear svg {
  width: 1.25rem;
  height: 1.25rem;
  fill: currentcolor;
}

.civic-select-field__clear:disabled {
  cursor: default;
}

.civic-select-field--floating .usa-label {
  position: absolute;
  z-index: 1;
  top: 50%;
  left: 0.75rem;
  margin: 0;
  transform: translateY(-50%);
  pointer-events: none;
  transition:
    top 120ms ease,
    font-size 120ms ease,
    transform 120ms ease;
}

.civic-select-field--floating.civic-select-field--filled .usa-label,
.civic-select-field--floating
  .civic-select-field__input:focus-within
  .usa-label {
  top: 0;
  padding: 0 0.25rem;
  transform: translateY(-50%);
  font-size: 0.75rem;
  line-height: 1;
}

.civic-select-field .usa-hint {
  color: var(--civic-color-ink-muted);
}

.civic-select-field--inverse .usa-label {
  color: rgba(255, 255, 255, 0.9);
}

.civic-select-field--inverse.civic-select-field--floating
  .usa-label {
  background: #353d42;
}

.civic-select-field--inverse .civic-select-field__control {
  margin-top: 0;
  border: 1px solid rgba(255, 255, 255, 0.38);
  border-radius: 4px;
  color: rgba(255, 255, 255, 0.82);
  background-color: #353d42;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'%3E%3Cpath d='M2 4l4 4 4-4' fill='none' stroke='%23fff' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  background-position: right 0.5rem center;
  background-size: 0.75rem 0.75rem;
  transition: border-color 120ms ease, background-color 120ms ease;
}

.civic-select-field--inverse .civic-select-field__control:hover:not(:disabled) {
  border-color: rgba(255, 255, 255, 0.9);
  background-color: rgba(255, 255, 255, 0.04);
}

.civic-select-field--inverse .civic-select-field__control:disabled {
  color: rgba(255, 255, 255, 0.64);
  background-color: #565c65;
}

.civic-select-field--inverse .civic-select-field__clear {
  color: rgba(255, 255, 255, 0.82);
}

.civic-select-field--inverse .civic-select-field__clear:hover:not(:disabled) {
  color: #ffffff;
}

.civic-select-field--inverse .civic-select-field__clear:disabled {
  color: rgba(255, 255, 255, 0.64);
}

.civic-select-field--inverse .usa-hint {
  margin: 0.5rem 0 0;
  color: rgba(255, 255, 255, 0.62);
  font-size: 0.75rem;
  line-height: 1;
}

@media (forced-colors: active) {
  .civic-select-field--inverse .civic-select-field__control {
    padding-right: 0;
    background-image: none;
  }

  .civic-select-field--inverse.civic-select-field--clearable
    .civic-select-field__control {
    padding-right: 4rem;
  }

  .civic-select-field--inverse.civic-select-field--floating
    .usa-label {
    background: Canvas;
  }
}
</style>
