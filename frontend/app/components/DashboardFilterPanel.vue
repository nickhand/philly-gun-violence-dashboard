<script setup lang="ts">
import CivicDisclosurePanel from "../../layers/civic-ui/app/components/CivicDisclosurePanel.vue";

withDefaults(
  defineProps<{
    disabled?: boolean;
    modified: boolean;
    title: string;
  }>(),
  { disabled: false },
);

const emit = defineEmits<{
  reset: [];
}>();
</script>

<template>
  <CivicDisclosurePanel :title="title">
    <slot />
    <template #action>
      <button
        v-if="modified"
        class="civic-dashboard-filter-panel__reset"
        type="button"
        :disabled="disabled"
        :aria-label="`Reset ${title} filter`"
        @click="emit('reset')"
      >
        Reset
      </button>
    </template>
  </CivicDisclosurePanel>
</template>

<style scoped>
.civic-dashboard-filter-panel__reset {
  position: absolute;
  z-index: 1;
  top: 0;
  right: 3.25rem;
  display: inline-flex;
  height: 3.65rem;
  margin: 0;
  padding: 0 0.5rem;
  align-items: center;
  border: 0;
  color: inherit;
  background: transparent;
  cursor: pointer;
  font: inherit;
  line-height: 1;
}

.civic-dashboard-filter-panel__reset:not(:disabled):hover {
  color: #7ab5e5;
}

.civic-dashboard-filter-panel__reset:disabled {
  cursor: default;
  opacity: 0.4;
}
</style>
