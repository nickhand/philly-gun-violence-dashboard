<script setup lang="ts">
import { computed } from "vue";

defineOptions({ inheritAttrs: false });

const props = withDefaults(
  defineProps<{
    filename?: string;
    format: string;
    href: string;
    sizeBytes?: number | null;
    variant?: "button" | "link";
  }>(),
  {
    filename: undefined,
    sizeBytes: null,
    variant: "link",
  },
);

function formatFileSize(bytes: number): string {
  if (bytes < 1_000) return `${bytes} B`;

  const units = ["KB", "MB", "GB"] as const;
  let value = bytes / 1_000;
  let unitIndex = 0;
  while (value >= 1_000 && unitIndex < units.length - 1) {
    value /= 1_000;
    unitIndex += 1;
  }

  return `${new Intl.NumberFormat("en-US", {
    maximumFractionDigits: value < 10 ? 1 : 0,
  }).format(value)} ${units[unitIndex]}`;
}

const metadata = computed(() => {
  const size =
    typeof props.sizeBytes === "number" &&
    Number.isFinite(props.sizeBytes) &&
    props.sizeBytes >= 0
      ? formatFileSize(props.sizeBytes)
      : null;
  return `[${[props.format.toUpperCase(), size].filter(Boolean).join(", ")}]`;
});
</script>

<template>
  <a
    v-bind="$attrs"
    class="civic-file-download-link"
    :class="
      variant === 'button'
        ? ['usa-button', 'civic-file-download-link--button']
        : undefined
    "
    :download="filename"
    :href="href"
  >
    <CivicIcon name="file-download" />
    <span class="civic-file-download-link__label"><slot /></span>
    <span class="civic-file-download-link__metadata">{{ metadata }}</span>
  </a>
</template>

<style scoped>
.civic-file-download-link {
  display: inline-grid;
  max-width: 100%;
  min-width: 0;
  grid-template-areas:
    "icon label"
    ". metadata";
  grid-template-columns: auto minmax(0, 1fr);
  column-gap: 0.4rem;
  row-gap: 0.15rem;
  align-items: start;
  vertical-align: top;
}

.civic-file-download-link :deep(.civic-icon) {
  grid-area: icon;
  margin-top: 0.18em;
  font-size: 1.1em;
}

.civic-file-download-link__label {
  min-width: 0;
  grid-area: label;
  overflow-wrap: anywhere;
}

.civic-file-download-link__metadata {
  min-width: 0;
  grid-area: metadata;
  white-space: nowrap;
}

.civic-file-download-link--button {
  display: inline-grid;
  max-width: 100%;
  min-width: 0;
  grid-template-areas: "icon label metadata";
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 0.4rem;
  align-items: center;
  margin: 0;
}

.civic-file-download-link--button :deep(.civic-icon) {
  margin-top: 0;
}
</style>
