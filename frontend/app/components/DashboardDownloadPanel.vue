<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";

import { BOUNDARY_OVERLAYS } from "~/utils/mapOverlays";
import {
  createShootingDownload,
  type ShootingDownloadOptions,
} from "~/utils/shootingDownloads";
import type { ShootingRow } from "~/utils/shootingRecords";
import { track } from "~/utils/analytics";

const props = defineProps<{
  allRows: ShootingRow[];
  apiBaseUrl: string;
  filteredRows: ShootingRow[];
}>();

const dialog = ref<HTMLDialogElement | null>(null);
const trigger = ref<HTMLButtonElement | null>(null);
const selection = ref<"all" | "filtered">("filtered");
const format = ref<"csv" | "geojson">("geojson");
const formatLabel = computed(() =>
  format.value === "csv" ? "CSV" : "GeoJSON",
);
const aggregateBy = ref<ShootingDownloadOptions["aggregateBy"]>(null);
const state = ref<"idle" | "working" | "error">("idle");
const errorReason = ref<"failed" | "timeout" | null>(null);
const errorMessage = computed(() =>
  errorReason.value === "timeout"
    ? "The download took too long to prepare. Try again."
    : "The download could not be prepared. No empty file was substituted.",
);
const selectedCount = computed(() =>
  selection.value === "filtered"
    ? props.filteredRows.length
    : props.allRows.length,
);
const selectedAggregateLabel = computed(
  () =>
    BOUNDARY_OVERLAYS.find((overlay) => overlay.id === aggregateBy.value)
      ?.label ?? "",
);
const DOWNLOAD_TIMEOUT_MS = 15_000;
let preparationController: AbortController | null = null;
let preparationTimer: ReturnType<typeof setTimeout> | null = null;
let preparationId = 0;

function finishPreparation(id: number): void {
  if (id !== preparationId) return;
  if (preparationTimer) clearTimeout(preparationTimer);
  preparationTimer = null;
  preparationController = null;
}

function cancelPreparation(): void {
  preparationId += 1;
  if (preparationTimer) clearTimeout(preparationTimer);
  preparationTimer = null;
  preparationController?.abort();
  preparationController = null;
  if (state.value === "working") state.value = "idle";
}

function resetOptions(): void {
  selection.value = "filtered";
  format.value = "geojson";
  aggregateBy.value = null;
  state.value = "idle";
  errorReason.value = null;
}

function openDialog(): void {
  const element = dialog.value;
  if (!element || element.open) return;
  if (typeof element.showModal === "function") element.showModal();
  else element.setAttribute("open", "");
}

function closeDialog(): void {
  cancelPreparation();
  const element = dialog.value;
  if (!element) return;
  if (!element.open) {
    resetOptions();
    trigger.value?.focus();
    return;
  }
  if (typeof element.close === "function") {
    element.close();
    return;
  }
  element.removeAttribute("open");
  resetOptions();
  trigger.value?.focus();
}

function handleClose(): void {
  cancelPreparation();
  resetOptions();
  trigger.value?.focus();
}

function handleCancel(event: Event): void {
  event.preventDefault();
  closeDialog();
}

function handleDialogClick(event: MouseEvent): void {
  if (event.target === dialog.value) closeDialog();
}

function handleDialogKeydown(event: KeyboardEvent): void {
  if (event.key !== "Tab") return;
  const element = dialog.value;
  if (!element) return;

  const focusable = Array.from(
    element.querySelectorAll<HTMLElement>(
      "button:not([disabled]), input:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex='-1'])",
    ),
  );
  const first = focusable[0];
  const last = focusable.at(-1);
  if (!first || !last) return;

  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

async function download(): Promise<void> {
  if (state.value === "working") return;
  track("data_download_requested", {
    aggregate_by: aggregateBy.value,
    data_selection: selection.value,
    format: format.value,
    record_count: selectedCount.value,
    source_page: "explorer",
  });
  const id = ++preparationId;
  const controller = new AbortController();
  preparationController = controller;
  let timedOut = false;
  preparationTimer = setTimeout(() => {
    if (id !== preparationId) return;
    timedOut = true;
    controller.abort();
  }, DOWNLOAD_TIMEOUT_MS);
  state.value = "working";
  errorReason.value = null;
  try {
    const file = await createShootingDownload(
      props.apiBaseUrl,
      props.filteredRows,
      props.allRows,
      {
        aggregateBy: aggregateBy.value,
        format: format.value,
        useFiltered: selection.value === "filtered",
      },
      { signal: controller.signal },
    );
    if (id !== preparationId) return;
    if (controller.signal.aborted) {
      finishPreparation(id);
      if (timedOut) {
        errorReason.value = "timeout";
        state.value = "error";
      } else {
        state.value = "idle";
      }
      return;
    }
    if (!dialog.value?.open) {
      finishPreparation(id);
      state.value = "idle";
      return;
    }
    const url = URL.createObjectURL(new Blob([file.content], { type: file.type }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = file.filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    finishPreparation(id);
    state.value = "idle";
    closeDialog();
  } catch (error) {
    if (id !== preparationId) return;
    const aborted =
      controller.signal.aborted ||
      (error as { name?: string } | null)?.name === "AbortError";
    finishPreparation(id);
    if (timedOut) {
      errorReason.value = "timeout";
      state.value = "error";
    } else if (!aborted) {
      errorReason.value = "failed";
      state.value = "error";
    } else {
      state.value = "idle";
    }
  } finally {
    finishPreparation(id);
  }
}

onBeforeUnmount(cancelPreparation);
</script>

<template>
  <button
    ref="trigger"
    class="usa-button usa-button--outline civic-dashboard-download__trigger"
    type="button"
    aria-controls="dashboard-download-dialog"
    aria-haspopup="dialog"
    @click="openDialog"
  >
    <CivicIcon name="file-download" />
    Download Data
  </button>

  <dialog
    ref="dialog"
    id="dashboard-download-dialog"
    class="civic-dashboard-download"
    aria-labelledby="dashboard-download-title"
    aria-describedby="dashboard-download-description"
    :aria-busy="state === 'working'"
    @cancel="handleCancel"
    @click="handleDialogClick"
    @close="handleClose"
    @keydown="handleDialogKeydown"
  >
    <div class="civic-dashboard-download__header">
      <h2 id="dashboard-download-title">Download Data</h2>
    </div>
    <form @submit.prevent="download">
      <div class="civic-dashboard-download__content">
        <fieldset class="civic-dashboard-download__group">
          <legend class="civic-dashboard-download__label">
            Data Selection
          </legend>
          <div class="civic-dashboard-download__toggle">
            <input
              id="dashboard-download-filtered"
              v-model="selection"
              class="civic-dashboard-download__radio"
              name="dashboard-download-selection"
              type="radio"
              value="filtered"
              :disabled="state === 'working'"
            />
            <label
              class="civic-dashboard-download__option"
              for="dashboard-download-filtered"
            >
              <svg aria-hidden="true" viewBox="0 0 24 24">
                <path d="M3 5h18l-7 8v6l-4 2v-8L3 5z" />
              </svg>
              Filtered Data
            </label>
            <input
              id="dashboard-download-all"
              v-model="selection"
              class="civic-dashboard-download__radio"
              name="dashboard-download-selection"
              type="radio"
              value="all"
              :disabled="state === 'working'"
            />
            <label
              class="civic-dashboard-download__option"
              for="dashboard-download-all"
            >
              <svg aria-hidden="true" viewBox="0 0 24 24">
                <path
                  d="M12 3C7.58 3 4 4.34 4 6s3.58 3 8 3 8-1.34 8-3-3.58-3-8-3zm-8 6v3c0 1.66 3.58 3 8 3s8-1.34 8-3V9c-1.72 1.37-4.89 2-8 2s-6.28-.63-8-2zm0 6v3c0 1.66 3.58 3 8 3s8-1.34 8-3v-3c-1.72 1.37-4.89 2-8 2s-6.28-.63-8-2z"
                />
              </svg>
              All Data
            </label>
          </div>
          <p
            id="dashboard-download-description"
            class="civic-dashboard-download__hint"
          >
            <template v-if="selection === 'filtered'">
              Export {{ selectedCount.toLocaleString() }}
              {{ selectedCount === 1 ? "record" : "records" }} matching
              current filters
            </template>
            <template v-else>
              Export all {{ selectedCount.toLocaleString() }}
              {{ selectedCount === 1 ? "record" : "records" }}
            </template>
          </p>
        </fieldset>

        <fieldset class="civic-dashboard-download__group">
          <legend class="civic-dashboard-download__label">File Format</legend>
          <div class="civic-dashboard-download__toggle">
            <input
              id="dashboard-download-csv"
              v-model="format"
              class="civic-dashboard-download__radio"
              aria-describedby="dashboard-download-format-description"
              name="dashboard-download-format"
              type="radio"
              value="csv"
              :disabled="state === 'working'"
            />
            <label
              class="civic-dashboard-download__option"
              for="dashboard-download-csv"
            >
              <svg aria-hidden="true" viewBox="0 0 24 24">
                <path
                  d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm1 7V3.5L18.5 9H15zm-7 4h8v2H8v-2zm0 4h8v2H8v-2z"
                />
              </svg>
              CSV
            </label>
            <input
              id="dashboard-download-geojson"
              v-model="format"
              class="civic-dashboard-download__radio"
              aria-describedby="dashboard-download-format-description"
              name="dashboard-download-format"
              type="radio"
              value="geojson"
              :disabled="state === 'working'"
            />
            <label
              class="civic-dashboard-download__option"
              for="dashboard-download-geojson"
            >
              <svg aria-hidden="true" viewBox="0 0 24 24">
                <path
                  d="M12 2a7 7 0 0 0-7 7c0 5.25 7 13 7 13s7-7.75 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6a2.5 2.5 0 0 1 0 5.5z"
                />
              </svg>
              GeoJSON
            </label>
          </div>
          <p
            id="dashboard-download-format-description"
            class="civic-dashboard-download__hint"
          >
            {{
              format === "csv"
                ? "A table with latitude and longitude columns."
                : "Geographic format with coordinates"
            }}
          </p>
        </fieldset>

        <div class="civic-dashboard-download__group">
          <label
            class="civic-dashboard-download__label"
            for="dashboard-download-aggregate"
          >
            Aggregate By
            <span class="civic-dashboard-download__optional">(Optional)</span>
          </label>
          <div class="civic-dashboard-download__select-control">
            <select
              id="dashboard-download-aggregate"
              v-model="aggregateBy"
              class="civic-dashboard-download__select"
              :disabled="state === 'working'"
            >
              <option :value="null">No aggregation</option>
              <option
                v-for="overlay in BOUNDARY_OVERLAYS"
                :key="overlay.id"
                :value="overlay.id"
              >
                {{ overlay.label }}
              </option>
            </select>
            <svg aria-hidden="true" viewBox="0 0 24 24">
              <path d="m7 10 5 5 5-5z" />
            </svg>
          </div>
          <p v-if="aggregateBy" class="civic-dashboard-download__hint">
            Data will be summarized by {{ selectedAggregateLabel }}
          </p>
        </div>

        <p
          v-if="state === 'error'"
          class="civic-dashboard-download__error"
          role="alert"
        >
          {{ errorMessage }}
        </p>
      </div>

      <div class="civic-dashboard-download__actions">
        <button
          class="civic-dashboard-download__cancel"
          type="button"
          @click="closeDialog"
        >
          Cancel
        </button>
        <button
          class="civic-dashboard-download__submit"
          type="submit"
          :disabled="state === 'working'"
        >
          <CivicIcon name="file-download" />
          {{
            state === "working"
              ? `Preparing ${formatLabel}…`
              : `Download ${formatLabel}`
          }}
        </button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
.civic-dashboard-download__trigger {
  width: 100%;
  margin: 0;
}

.civic-dashboard-download {
  box-sizing: border-box;
  width: min(30rem, calc(100% - 2rem));
  max-width: none;
  max-height: calc(100dvh - 2rem);
  padding: 0;
  overflow: auto;
  border: 0;
  border-radius: 0.75rem;
  color: var(--civic-color-ink);
  background: #2d3339;
  box-shadow:
    0 11px 15px -7px rgba(0, 0, 0, 0.2),
    0 24px 38px 3px rgba(0, 0, 0, 0.14),
    0 9px 46px 8px rgba(0, 0, 0, 0.12);
}

.civic-dashboard-download::backdrop {
  background: rgba(0, 0, 0, 0.5);
}

.civic-dashboard-download__header {
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(0, 0, 0, 0.2);
}

.civic-dashboard-download__header h2 {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  margin: 0;
  color: rgba(255, 255, 255, 0.95);
  font-size: 1.35rem;
  font-weight: 600;
  line-height: 1.6;
}

.civic-dashboard-download form {
  display: block;
  padding: 0;
}

.civic-dashboard-download__content {
  padding: 1.75rem 1.5rem;
}

.civic-dashboard-download__group {
  min-width: 0;
  padding: 0;
  margin: 0 0 1.75rem;
  border: 0;
}

.civic-dashboard-download__group:last-child {
  margin-bottom: 0;
}

.civic-dashboard-download__label {
  display: block;
  padding: 0;
  margin: 0 0 0.875rem;
  color: rgba(255, 255, 255, 0.9);
  font-size: 0.95rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  line-height: 1.5;
}

.civic-dashboard-download__optional {
  margin-left: 0.375rem;
  color: rgba(255, 255, 255, 0.7);
  font-size: 0.85rem;
  font-weight: 400;
}

.civic-dashboard-download__toggle {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.civic-dashboard-download__radio {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}

.civic-dashboard-download__option {
  display: flex;
  height: 3rem;
  gap: 0.625rem;
  align-items: center;
  justify-content: center;
  padding: 0 1rem;
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #ffffff;
  background: rgba(0, 0, 0, 0.15);
  cursor: pointer;
  font-size: 0.95rem;
  font-weight: 500;
  line-height: 1;
}

.civic-dashboard-download__radio:first-child
  + .civic-dashboard-download__option {
  border-radius: 0.5rem 0 0 0.5rem;
}

.civic-dashboard-download__radio:nth-of-type(2)
  + .civic-dashboard-download__option {
  border-radius: 0 0.5rem 0.5rem 0;
}

.civic-dashboard-download__radio:checked
  + .civic-dashboard-download__option {
  z-index: 1;
  border-color: #ffffff;
  color: #ffffff;
  background: rgba(255, 255, 255, 0.2);
}

.civic-dashboard-download__radio:focus-visible
  + .civic-dashboard-download__option {
  z-index: 2;
  outline: 3px solid var(--civic-color-focus);
  outline-offset: 2px;
}

.civic-dashboard-download__radio:not(:disabled)
  + .civic-dashboard-download__option:hover {
  border-color: rgba(255, 255, 255, 0.55);
  background: rgba(255, 255, 255, 0.08);
}

.civic-dashboard-download__radio:checked:not(:disabled)
  + .civic-dashboard-download__option:hover {
  border-color: #ffffff;
  background: rgba(255, 255, 255, 0.24);
}

.civic-dashboard-download__radio:disabled
  + .civic-dashboard-download__option {
  cursor: wait;
  opacity: 0.55;
}

.civic-dashboard-download__option svg {
  width: 1.1rem;
  height: 1.1rem;
  flex: 0 0 auto;
  fill: currentColor;
  opacity: 0.8;
}

.civic-dashboard-download__radio:checked
  + .civic-dashboard-download__option
  svg {
  opacity: 1;
}

.civic-dashboard-download__hint {
  margin: 0.625rem 0 0;
  color: rgba(255, 255, 255, 0.72);
  font-size: 0.8rem;
  font-weight: 400;
  line-height: 1.5;
}

.civic-dashboard-download__select-control {
  position: relative;
}

.civic-dashboard-download__select {
  width: 100%;
  height: 3rem;
  padding: 0 2.75rem 0 1rem;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 0.5rem;
  color: #ffffff;
  background: rgba(0, 0, 0, 0.2);
  cursor: pointer;
  appearance: none;
  font: inherit;
  font-size: 0.95rem;
  line-height: 1.5;
}

.civic-dashboard-download__select:hover:not(:disabled) {
  border-color: rgba(255, 255, 255, 0.55);
  background: rgba(255, 255, 255, 0.04);
}

.civic-dashboard-download__select:disabled {
  cursor: wait;
  opacity: 0.55;
}

.civic-dashboard-download__select:focus {
  border-color: #ffffff;
}

.civic-dashboard-download__select-control > svg {
  position: absolute;
  top: 50%;
  right: 0.875rem;
  width: 1.25rem;
  height: 1.25rem;
  fill: rgba(255, 255, 255, 0.7);
  pointer-events: none;
  transform: translateY(-50%);
}

.civic-dashboard-download__error {
  padding: 0.75rem;
  margin: 1rem 0 0;
  border-left: 0.25rem solid var(--civic-color-fatal);
  color: var(--civic-color-ink);
  background: rgba(0, 0, 0, 0.2);
  font-size: 0.875rem;
}

.civic-dashboard-download__actions {
  display: flex;
  align-items: center;
  min-height: 4.75rem;
  padding: 1rem 1.25rem;
  border-top: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(0, 0, 0, 0.1);
}

.civic-dashboard-download__cancel,
.civic-dashboard-download__submit {
  display: inline-flex;
  min-height: 2.75rem;
  align-items: center;
  justify-content: center;
  margin: 0;
  border: 0;
  border-radius: 0.25rem;
  cursor: pointer;
  font: inherit;
  font-size: 1rem;
  font-weight: 500;
  line-height: 1;
}

.civic-dashboard-download__cancel {
  padding: 0 1.5rem;
  color: #ffffff;
  background: transparent;
}

.civic-dashboard-download__cancel:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.08);
}

.civic-dashboard-download__submit {
  gap: 0.5rem;
  padding: 0 1.5rem;
  margin-left: auto;
  color: #000000;
  background: #ffffff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

.civic-dashboard-download__submit:hover:not(:disabled) {
  background: #dfe1e2;
}

.civic-dashboard-download__submit svg {
  width: 1.15rem;
  height: 1.15rem;
  fill: currentColor;
}

.civic-dashboard-download__cancel:disabled,
.civic-dashboard-download__submit:disabled {
  cursor: wait;
  opacity: 0.55;
}

@media (forced-colors: active) {
  .civic-dashboard-download__radio:disabled
    + .civic-dashboard-download__option,
  .civic-dashboard-download__select:disabled {
    opacity: 1;
  }

  .civic-dashboard-download__radio:checked
    + .civic-dashboard-download__option {
    border-color: Highlight;
    color: HighlightText;
    background: Highlight;
    forced-color-adjust: none;
  }

  .civic-dashboard-download__radio:checked
    + .civic-dashboard-download__option::after {
    margin-left: 0.25rem;
    content: "✓";
    font-weight: 700;
  }
}

@media (max-width: 30rem) {
  .civic-dashboard-download__actions {
    gap: 0.75rem;
    padding-inline: 1rem;
  }

  .civic-dashboard-download__cancel {
    flex: 0 0 auto;
    padding-inline: 0.75rem;
  }

  .civic-dashboard-download__submit {
    flex: 1 1 0;
    min-width: 0;
    padding-inline: 0.75rem;
    margin-left: 0;
    white-space: nowrap;
  }
}

@media (max-width: 26rem) {
  .civic-dashboard-download__header {
    padding-inline: 1.25rem;
  }

  .civic-dashboard-download__content {
    padding-inline: 1.25rem;
  }

  .civic-dashboard-download__option {
    gap: 0.4rem;
    padding-inline: 0.5rem;
    font-size: 0.875rem;
  }

  .civic-dashboard-download__option svg {
    width: 1rem;
    height: 1rem;
  }
}

@media (max-width: 22rem) {
  .civic-dashboard-download__actions {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }

  .civic-dashboard-download__cancel,
  .civic-dashboard-download__submit {
    width: 100%;
  }
}
</style>
