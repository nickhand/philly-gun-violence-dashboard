<script setup lang="ts">
defineProps<{
  name: "file-download";
}>();
</script>

<template>
  <svg
    class="usa-icon civic-icon"
    aria-hidden="true"
    focusable="false"
    viewBox="0 0 24 24"
  >
    <path
      v-if="name === 'file-download'"
      d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"
    />
  </svg>
</template>

<style scoped>
.civic-icon {
  width: 1em;
  height: 1em;
  flex: 0 0 auto;
  fill: currentColor;
}
</style>
