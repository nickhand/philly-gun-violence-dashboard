<template>
  <v-expansion-panel class="filter-panel" elevation="0">
    <template v-if="hideActions">
      <div class="switch-panel-title">
        <slot name="title" />
      </div>
    </template>
    <template v-else>
      <div class="filter-header">
        <v-expansion-panel-title :ripple="false">
          <span>{{ label }}</span>
        </v-expansion-panel-title>
        <button
          v-if="showReset"
          type="button"
          class="reset-button"
          :aria-label="`Reset ${label} filter`"
          @click="$emit('reset')"
        >
          Reset
        </button>
      </div>
    </template>
    <v-expansion-panel-text v-if="$slots.default">
      <slot />
    </v-expansion-panel-text>
  </v-expansion-panel>
</template>

<script setup lang="ts">
/**
 * FilterPanel Component
 *
 * Base wrapper for filter expansion panels.
 * Provides consistent styling and optional reset link.
 *
 * @component
 */

defineProps<{
  /** Filter label displayed in panel title */
  label?: string;
  /** Whether to show the reset link */
  showReset?: boolean;
  /** Whether to hide the expand/collapse actions (for switch filters) */
  hideActions?: boolean;
}>();

defineEmits<{
  /** Emitted when reset link is clicked */
  reset: [];
}>();
</script>

<style scoped>
.filter-panel {
  background-color: rgb(var(--v-theme-background)) !important;
  color: #fff !important;
}

.filter-header {
  display: flex;
  align-items: center;
  width: 100%;
}

.filter-header :deep(.v-expansion-panel-title) {
  flex: 1;
}

.reset-button {
  color: #7ab5e5;
  font-weight: 500;
  cursor: pointer;
  margin-right: 0.75rem;
  padding: 0.5rem;
  background: transparent;
  border: 0;
  border-radius: 4px;
}

.reset-button:hover {
  text-decoration: underline;
}

.switch-panel-title {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: flex-start;
  min-height: 44px;
  padding: 4px 24px;
}
</style>
