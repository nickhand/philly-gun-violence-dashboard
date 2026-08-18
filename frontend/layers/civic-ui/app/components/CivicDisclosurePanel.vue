<script setup lang="ts">
defineOptions({ inheritAttrs: false });

defineProps<{
  title: string;
}>();
</script>

<template>
  <div class="civic-disclosure-panel-shell">
    <details v-bind="$attrs" class="civic-disclosure-panel">
      <summary>{{ title }}</summary>
      <slot />
    </details>
    <slot name="action" />
  </div>
</template>

<style scoped>
.civic-disclosure-panel-shell {
  position: relative;
}

.civic-disclosure-panel {
  border-bottom: 1px solid color-mix(in srgb, currentColor 20%, transparent);
  color: inherit;
}

.civic-disclosure-panel > summary {
  display: flex;
  box-sizing: border-box;
  min-height: 3.15rem;
  padding: 1rem 1.5rem;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  color: inherit;
  cursor: pointer;
  font-size: 1.1rem;
  font-weight: 400;
  line-height: 1;
  list-style: none;
  transition: background-color 120ms ease;
}

.civic-disclosure-panel > summary:hover {
  background: rgba(255, 255, 255, 0.04);
}

.civic-disclosure-panel > summary::-webkit-details-marker {
  display: none;
}

.civic-disclosure-panel > summary::after {
  width: 1.65rem;
  height: 1.65rem;
  flex: 0 0 1.65rem;
  background: currentColor;
  clip-path: polygon(
    30.875% 35.75%,
    50% 54.875%,
    69.125% 35.75%,
    75% 41.667%,
    50% 66.667%,
    25% 41.667%
  );
  content: "";
  transition: transform 150ms ease;
}

.civic-disclosure-panel[open] > summary::after {
  transform: rotate(180deg);
}

@media (forced-colors: active) {
  .civic-disclosure-panel > summary::after {
    width: 0.75rem;
    height: 0.75rem;
    border-right: 0.2rem solid ButtonText;
    border-bottom: 0.2rem solid ButtonText;
    background: none;
    clip-path: none;
    transform: rotate(45deg);
  }

  .civic-disclosure-panel[open] > summary::after {
    transform: rotate(225deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .civic-disclosure-panel > summary::after {
    transition: none;
  }

  .civic-disclosure-panel > summary {
    transition: none;
  }
}
</style>
