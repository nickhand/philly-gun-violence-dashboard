<script setup lang="ts">
import { computed, useAttrs, useId } from "vue";

defineOptions({ inheritAttrs: false });

type RangeFieldDensity = "default" | "compact";
type RangeFieldTone = "default" | "inverse";

const props = withDefaults(
  defineProps<{
    modelValue: number;
    label: string;
    id?: string;
    min?: number;
    max?: number;
    step?: number;
    formatValue?: (value: number) => string;
    tone?: RangeFieldTone;
    density?: RangeFieldDensity;
    disabled?: boolean;
  }>(),
  {
    id: undefined,
    min: 0,
    max: 100,
    step: 1,
    formatValue: undefined,
    tone: "default",
    density: "default",
    disabled: false,
  },
);

const emit = defineEmits<{
  "update:modelValue": [value: number];
}>();

const generatedId = `civic-range-field-${useId()}`;
const attrs = useAttrs();
const controlId = computed(() => props.id ?? generatedId);
const formattedValue = computed(() =>
  props.formatValue
    ? props.formatValue(props.modelValue)
    : String(props.modelValue),
);

function updateValue(event: Event): void {
  if (props.disabled) return;
  const value = (event.currentTarget as HTMLInputElement).valueAsNumber;
  if (Number.isFinite(value)) emit("update:modelValue", value);
}
</script>

<template>
  <div
    class="civic-range-field"
    :class="[
      `civic-range-field--${tone}`,
      `civic-range-field--${density}`,
    ]"
  >
    <label class="usa-label civic-range-field__label" :for="controlId">
      <span>{{ label }}</span>
      <output
        class="civic-range-field__value"
        :for="controlId"
        aria-hidden="true"
      >
        {{ formattedValue }}
      </output>
    </label>
    <input
      v-bind="attrs"
      :id="controlId"
      class="usa-range civic-range-field__input"
      type="range"
      :min="min"
      :max="max"
      :step="step"
      :value="modelValue"
      :disabled="disabled"
      :aria-valuetext="formattedValue"
      @input="updateValue"
    />
  </div>
</template>

<style scoped>
.civic-range-field {
  --civic-range-field-label-color: inherit;
  --civic-range-field-value-color: var(--civic-color-ink-muted, #565c65);
  --civic-range-field-track-color: #a9b2b7;
  --civic-range-field-thumb-border-color: #565c65;
  --civic-range-field-thumb-color: #ffffff;
  --civic-range-field-focus-color: var(--civic-color-focus, #005ea8);

  min-width: 0;
  color: inherit;
  background: transparent;
}

.civic-range-field--inverse {
  --civic-range-field-label-color: rgba(255, 255, 255, 0.9);
  --civic-range-field-value-color: rgba(255, 255, 255, 0.72);
}

.civic-range-field__label {
  display: flex;
  max-width: none;
  gap: 1rem;
  align-items: baseline;
  justify-content: space-between;
  margin-top: 1rem;
  color: var(--civic-range-field-label-color);
  font-weight: 400;
}

.civic-range-field__value {
  flex: none;
  color: var(--civic-range-field-value-color);
  font-variant-numeric: tabular-nums;
}

.civic-range-field__input {
  display: block;
  box-sizing: border-box;
  width: 100%;
  max-width: none;
  height: 2.5rem;
  margin: 0.5rem 0 0;
  padding: 0 0.125rem;
  appearance: none;
  border: 0;
  color: inherit;
  background: transparent;
}

.civic-range-field--compact .civic-range-field__input {
  height: 2rem;
  margin-top: 0.25rem;
}

.civic-range-field--compact .civic-range-field__label {
  font-size: 0.95rem;
}

.civic-range-field__input::-webkit-slider-runnable-track {
  width: 100%;
  height: 0.25rem;
  border: 0;
  border-radius: 99rem;
  background: var(--civic-range-field-track-color);
  cursor: pointer;
}

.civic-range-field__input::-moz-range-track {
  width: 100%;
  height: 0.25rem;
  border: 0;
  border-radius: 99rem;
  background: var(--civic-range-field-track-color);
  cursor: pointer;
}

.civic-range-field__input::-webkit-slider-thumb {
  box-sizing: border-box;
  width: 1.125rem;
  height: 1.125rem;
  margin-top: -0.4375rem;
  appearance: none;
  border: 2px solid var(--civic-range-field-thumb-border-color);
  border-radius: 50%;
  background: var(--civic-range-field-thumb-color);
  box-shadow: none;
  cursor: pointer;
}

.civic-range-field__input::-moz-range-thumb {
  box-sizing: border-box;
  width: 1.125rem;
  height: 1.125rem;
  border: 2px solid var(--civic-range-field-thumb-border-color);
  border-radius: 50%;
  background: var(--civic-range-field-thumb-color);
  box-shadow: none;
  cursor: pointer;
}

.civic-range-field__input:focus {
  outline: 0 !important;
}

.civic-range-field__input:disabled,
.civic-range-field__input:disabled::-webkit-slider-runnable-track,
.civic-range-field__input:disabled::-moz-range-track,
.civic-range-field__input:disabled::-webkit-slider-thumb,
.civic-range-field__input:disabled::-moz-range-thumb {
  cursor: default;
}

.civic-range-field__input:disabled {
  opacity: 0.65;
}

.civic-range-field__input:focus:not(:focus-visible)::-webkit-slider-thumb {
  box-shadow: none;
}

.civic-range-field__input:focus:not(:focus-visible)::-moz-range-thumb {
  box-shadow: none;
}

.civic-range-field__input:focus-visible::-webkit-slider-thumb {
  box-shadow: 0 0 0 3px var(--civic-range-field-focus-color);
}

.civic-range-field__input:focus-visible::-moz-range-thumb {
  box-shadow: 0 0 0 3px var(--civic-range-field-focus-color);
}

@media (forced-colors: active) {
  .civic-range-field__value {
    color: CanvasText;
  }

  .civic-range-field__input:focus-visible {
    outline: 2px solid Highlight !important;
    outline-offset: 2px !important;
  }

  .civic-range-field__input::-webkit-slider-runnable-track {
    background: CanvasText;
  }

  .civic-range-field__input::-moz-range-track {
    background: CanvasText;
  }

  .civic-range-field__input::-webkit-slider-thumb {
    border-color: ButtonText;
    background: Canvas;
  }

  .civic-range-field__input::-moz-range-thumb {
    border-color: ButtonText;
    background: Canvas;
  }

  .civic-range-field__input:disabled {
    opacity: 1;
  }

  .civic-range-field__input:disabled::-webkit-slider-runnable-track,
  .civic-range-field__input:disabled::-moz-range-track,
  .civic-range-field__input:disabled::-webkit-slider-thumb,
  .civic-range-field__input:disabled::-moz-range-thumb {
    border-color: GrayText;
    background: GrayText;
  }
}
</style>
