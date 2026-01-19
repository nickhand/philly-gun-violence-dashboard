<template>
  <v-expansion-panel class="filter-panel" elevation="0">
    <v-expansion-panel-title
      :ripple="false"
      :hide-actions="hideActions"
      :class="{ 'switch-panel-title': hideActions }"
    >
      <template v-if="hideActions">
        <slot name="title" />
      </template>
      <template v-else>
        <div class="filter-header">
          <span>{{ label }}</span>
          <span
            v-if="showReset"
            class="reset-link"
            @click.stop="$emit('reset')"
          >
            Reset
          </span>
        </div>
      </template>
    </v-expansion-panel-title>
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
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.reset-link {
  color: #7ab5e5;
  font-weight: 500;
  cursor: pointer;
  margin-right: 1rem;
}

.reset-link:hover {
  text-decoration: underline;
}

.switch-panel-title {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: flex-start;
}
</style>
