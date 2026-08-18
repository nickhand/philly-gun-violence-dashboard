<script setup lang="ts">
import { computed, ref, useId } from "vue";

const props = withDefaults(
  defineProps<{
    label: string;
    tone?: "default" | "inverse";
    tooltipId?: string;
  }>(),
  {
    tone: "default",
    tooltipId: undefined,
  },
);

const generatedId = useId();
const hovered = ref(false);
const focused = ref(false);
const activated = ref(false);
const dismissed = ref(false);
const resolvedTooltipId = computed(
  () => props.tooltipId ?? `civic-info-tooltip-${generatedId}`,
);
const open = computed(
  () =>
    !dismissed.value &&
    (hovered.value || focused.value || activated.value),
);

function setHovered(value: boolean): void {
  hovered.value = value;
  if (value) dismissed.value = false;
  else if (!focused.value) activated.value = false;
}

function setFocused(value: boolean): void {
  focused.value = value;
  if (value) dismissed.value = false;
  else if (!hovered.value) activated.value = false;
}

function show(): void {
  activated.value = true;
  dismissed.value = false;
}

function dismiss(): void {
  activated.value = false;
  dismissed.value = true;
}
</script>

<template>
  <span
    class="civic-info-tooltip"
    :class="[
      `civic-info-tooltip--${tone}`,
      { 'civic-info-tooltip--open': open },
    ]"
    @pointerenter="setHovered(true)"
    @pointerleave="setHovered(false)"
  >
    <button
      type="button"
      class="civic-info-tooltip__trigger"
      :aria-describedby="resolvedTooltipId"
      @blur="setFocused(false)"
      @click="show"
      @focus="setFocused(true)"
      @keydown.esc.stop.prevent="dismiss"
    >
      <span aria-hidden="true">i</span>
      <span class="usa-sr-only">{{ label }}</span>
    </button>
    <span
      :id="resolvedTooltipId"
      v-show="open"
      class="civic-info-tooltip__panel"
      role="tooltip"
    >
      <slot />
    </span>
  </span>
</template>

<style scoped>
.civic-info-tooltip {
  --civic-info-tooltip-trigger-border: #005ea8;
  --civic-info-tooltip-trigger-color: #005ea8;
  --civic-info-tooltip-panel-border: rgba(27, 27, 27, 0.2);
  --civic-info-tooltip-panel-color: #1b1b1b;
  --civic-info-tooltip-panel-surface: #ffffff;
  --civic-info-tooltip-panel-shadow: 0 4px 12px rgba(0, 0, 0, 0.16);

  position: static;
  display: inline-flex;
  padding-block: 0.25rem;
  align-items: center;
  margin-block: -0.25rem;
  margin-inline-start: 0.4rem;
  vertical-align: middle;
}

.civic-info-tooltip--inverse {
  --civic-info-tooltip-trigger-border: rgba(255, 255, 255, 0.58);
  --civic-info-tooltip-trigger-color: rgba(255, 255, 255, 0.86);
  --civic-info-tooltip-panel-border: rgba(255, 255, 255, 0.28);
  --civic-info-tooltip-panel-color: rgba(255, 255, 255, 0.9);
  --civic-info-tooltip-panel-surface: #1d2428;
  --civic-info-tooltip-panel-shadow: 0 4px 12px rgba(0, 0, 0, 0.32);
}

.civic-info-tooltip__trigger {
  display: inline-flex;
  width: 1.5rem;
  height: 1.5rem;
  padding: 0;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--civic-info-tooltip-trigger-border);
  border-radius: 50%;
  color: var(--civic-info-tooltip-trigger-color);
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 0.78rem;
  font-weight: 700;
  line-height: 1;
}

.civic-info-tooltip__panel {
  position: absolute;
  z-index: 3;
  top: calc(100% + 0.5rem);
  right: 0;
  left: 0;
  box-sizing: border-box;
  width: auto;
  max-width: none;
  margin: 0;
  padding: 0.75rem 0.85rem;
  border: 1px solid var(--civic-info-tooltip-panel-border);
  border-radius: 4px;
  color: var(--civic-info-tooltip-panel-color);
  background: var(--civic-info-tooltip-panel-surface);
  box-shadow: var(--civic-info-tooltip-panel-shadow);
  font-size: 0.82rem;
  font-weight: 400;
  line-height: 1.5;
  overflow-wrap: anywhere;
  pointer-events: auto;
  text-align: left;
}

.civic-info-tooltip__panel::before {
  position: absolute;
  right: 0;
  bottom: 100%;
  left: 0;
  height: 0.5rem;
  content: "";
}
</style>
