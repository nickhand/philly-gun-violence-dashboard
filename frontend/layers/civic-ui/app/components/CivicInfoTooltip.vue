<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref,
  useId,
} from "vue";

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
const rootElement = ref<HTMLElement | null>(null);
const triggerElement = ref<HTMLButtonElement | null>(null);
const hovered = ref(false);
const focused = ref(false);
const activated = ref(false);
const dismissed = ref(false);
const resolvedTooltipId = computed(
  () => props.tooltipId ?? `civic-info-tooltip-${generatedId}`,
);
const informationSubject = computed(() =>
  props.label.replace(/^About\s+/i, "").trim(),
);
const dialogLabel = computed(() => `${informationSubject.value} information`);
const closeLabel = computed(() => `Close ${dialogLabel.value}`);
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

function handleFocusIn(): void {
  focused.value = true;
  dismissed.value = false;
}

function handleFocusOut(event: FocusEvent): void {
  const nextTarget = event.relatedTarget;
  if (
    nextTarget instanceof Node &&
    rootElement.value?.contains(nextTarget)
  ) {
    return;
  }

  focused.value = false;
  if (!hovered.value) activated.value = false;
}

function show(): void {
  activated.value = true;
  dismissed.value = false;
}

function dismiss(restoreTriggerFocus = false): void {
  if (restoreTriggerFocus) {
    triggerElement.value?.focus({ preventScroll: true });
  }
  activated.value = false;
  dismissed.value = true;
}

function toggle(): void {
  if (activated.value) dismiss();
  else show();
}

function handleDocumentPointerDown(event: Event): void {
  if (!open.value || !rootElement.value) return;
  if (event.composedPath().includes(rootElement.value)) return;
  dismiss();
}

onMounted(() => {
  document.addEventListener("pointerdown", handleDocumentPointerDown, true);
});

onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", handleDocumentPointerDown, true);
});
</script>

<template>
  <span
    ref="rootElement"
    class="civic-info-tooltip"
    :class="[
      `civic-info-tooltip--${tone}`,
      { 'civic-info-tooltip--open': open },
    ]"
    @focusin="handleFocusIn"
    @focusout="handleFocusOut"
    @keydown.esc.stop.prevent="dismiss(true)"
    @pointerenter="setHovered(true)"
    @pointerleave="setHovered(false)"
  >
    <button
      ref="triggerElement"
      type="button"
      class="civic-info-tooltip__trigger"
      :aria-controls="resolvedTooltipId"
      :aria-describedby="activated ? undefined : resolvedTooltipId"
      :aria-expanded="activated"
      aria-haspopup="dialog"
      @click="toggle"
    >
      <span aria-hidden="true">i</span>
      <span class="usa-sr-only">{{ label }}</span>
    </button>
    <span
      :id="resolvedTooltipId"
      v-show="open"
      class="civic-info-tooltip__panel"
      :class="{
        'civic-info-tooltip__panel--interactive': activated,
      }"
      :role="activated ? 'dialog' : 'tooltip'"
      :aria-label="activated ? dialogLabel : undefined"
    >
      <slot />
      <button
        v-if="activated"
        type="button"
        class="civic-info-tooltip__close"
        :aria-label="closeLabel"
        @click="dismiss(true)"
      >
        <span aria-hidden="true">×</span>
      </button>
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
  --civic-info-tooltip-close-hover: rgba(27, 27, 27, 0.08);
  --civic-info-tooltip-focus: #2491ff;

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
  --civic-info-tooltip-close-hover: rgba(255, 255, 255, 0.12);
  --civic-info-tooltip-focus: #59b9de;
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
  min-height: 3rem;
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

.civic-info-tooltip__panel--interactive {
  padding-inline-end: 3.35rem;
}

.civic-info-tooltip__close {
  position: absolute;
  top: 0.125rem;
  right: 0.125rem;
  display: inline-flex;
  width: 2.75rem;
  height: 2.75rem;
  padding: 0;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 4px;
  color: inherit;
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 1.5rem;
  line-height: 1;
}

.civic-info-tooltip__close:hover {
  background: var(--civic-info-tooltip-close-hover);
}

.civic-info-tooltip__close:focus-visible {
  outline: 3px solid var(--civic-info-tooltip-focus);
  outline-offset: -3px;
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
