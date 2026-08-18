<script setup lang="ts">
import { computed, ref } from "vue";

const props = withDefaults(
  defineProps<{
    errorMessage?: string;
    label?: string;
    successMessage?: string;
    text: string;
  }>(),
  {
    errorMessage: "Could not copy. Select and copy the text manually.",
    label: "Copy",
    successMessage: "Copied to clipboard.",
  },
);

const copyState = ref<"idle" | "copying" | "copied" | "error">("idle");
const statusMessage = computed(() => {
  if (copyState.value === "copied") return props.successMessage;
  if (copyState.value === "error") return props.errorMessage;
  return "";
});

function fallbackCopy(
  text: string,
  restoreFocusTo: HTMLElement | null,
): boolean {
  if (typeof document === "undefined" || !document.body) return false;

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "0";
  textarea.style.left = "0";
  textarea.style.width = "1px";
  textarea.style.height = "1px";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);

  try {
    textarea.focus({ preventScroll: true });
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    textarea.remove();
    restoreFocusTo?.focus({ preventScroll: true });
  }
}

async function copy(event: MouseEvent): Promise<void> {
  if (copyState.value === "copying") return;
  copyState.value = "copying";
  const copyButton = event.currentTarget as HTMLElement | null;

  try {
    if (
      typeof navigator !== "undefined" &&
      typeof navigator.clipboard?.writeText === "function"
    ) {
      try {
        await navigator.clipboard.writeText(props.text);
        copyState.value = "copied";
        return;
      } catch {
        // Older Safari releases can expose the API but reject it. The
        // selection-based fallback still works when invoked by this click.
      }
    }

    copyState.value = fallbackCopy(props.text, copyButton)
      ? "copied"
      : "error";
  } catch {
    copyState.value = "error";
  }
}
</script>

<template>
  <div class="civic-copy-control">
    <button
      class="usa-button usa-button--outline civic-copy-button"
      type="button"
      :aria-disabled="copyState === 'copying' ? 'true' : undefined"
      @click="copy"
    >
      {{ copyState === "copying" ? "Copying…" : label }}
    </button>
    <span
      class="civic-copy-control__status"
      :class="{ 'civic-copy-control__status--error': copyState === 'error' }"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {{ statusMessage }}
    </span>
  </div>
</template>

<style scoped>
.civic-copy-control {
  display: flex;
  min-height: 2.5rem;
  flex-wrap: wrap;
  gap: 0.65rem 0.85rem;
  align-items: center;
}

.civic-copy-button {
  flex: 0 0 auto;
  margin: 0;
  box-shadow: inset 0 0 0 2px var(--civic-color-link);
  color: var(--civic-color-link);
}

.civic-copy-button:hover {
  box-shadow: inset 0 0 0 2px var(--civic-color-link-hover);
  color: var(--civic-color-link-hover);
}

.civic-copy-control__status {
  color: var(--civic-color-ink-muted);
  font-size: 0.9rem;
}

.civic-copy-control__status--error {
  color: var(--civic-color-ink);
}
</style>
