<template>
  <v-dialog
    v-model="isOpen"
    max-width="480"
    class="download-dialog"
    scrim="rgba(0, 0, 0, 0.95)"
  >
    <!-- Trigger Button -->
    <template #activator="{ props: activatorProps }">
      <v-btn
        v-bind="activatorProps"
        variant="outlined"
        color="white"
        block
        class="download-trigger"
      >
        <v-icon icon="mdi-download" class="mr-2" />
        Download Data
      </v-btn>
    </template>

    <!-- Dialog Content -->
    <v-card class="download-card">
      <v-card-title class="download-card__title">
        <v-icon icon="mdi-download" class="mr-3" />
        Download Data
      </v-card-title>

      <v-card-text class="download-card__content">
        <!-- Data Selection -->
        <div class="option-group">
          <div class="option-group__label">Data Selection</div>
          <v-btn-toggle
            v-model="dataSelection"
            mandatory
            color="primary"
            class="option-toggle"
          >
            <v-btn :value="'filtered'" variant="outlined">
              <v-icon icon="mdi-filter" class="mr-2" />
              Filtered Data
            </v-btn>
            <v-btn :value="'all'" variant="outlined">
              <v-icon icon="mdi-database" class="mr-2" />
              All Data
            </v-btn>
          </v-btn-toggle>
          <div class="option-hint">
            {{
              dataSelection === "filtered"
                ? `Export ${formatNumber(
                    filteredCount
                  )} records matching current filters`
                : `Export all ${formatNumber(totalCount)} records`
            }}
          </div>
        </div>

        <!-- File Format -->
        <div class="option-group">
          <div class="option-group__label">File Format</div>
          <v-btn-toggle
            v-model="fileFormat"
            mandatory
            color="primary"
            class="option-toggle"
          >
            <v-btn :value="'csv'" variant="outlined">
              <v-icon icon="mdi-file-delimited" class="mr-2" />
              CSV
            </v-btn>
            <v-btn :value="'geojson'" variant="outlined">
              <v-icon icon="mdi-map-marker" class="mr-2" />
              GeoJSON
            </v-btn>
          </v-btn-toggle>
          <div class="option-hint">
            {{
              fileFormat === "csv"
                ? "Spreadsheet-compatible format (no geometry)"
                : "Geographic format with coordinates"
            }}
          </div>
        </div>

        <!-- Aggregation (optional) -->
        <div v-if="overlayLayerNames.length > 0" class="option-group">
          <div class="option-group__label">
            Aggregate By
            <span class="option-group__optional">(Optional)</span>
          </div>
          <v-select
            v-model="aggregateBy"
            :items="aggregationOptions"
            item-title="title"
            item-value="value"
            placeholder="No aggregation"
            variant="outlined"
            density="comfortable"
            clearable
            hide-details
            class="aggregate-select"
          />
          <div v-if="aggregateBy" class="option-hint">
            Data will be summarized by {{ aggregateBy }}
          </div>
        </div>
      </v-card-text>

      <v-divider />

      <v-card-actions class="download-card__actions">
        <v-btn variant="text" size="large" @click="isOpen = false">
          Cancel
        </v-btn>
        <v-spacer />
        <v-btn
          color="primary"
          variant="elevated"
          size="large"
          :loading="isDownloading"
          @click="handleDownload"
        >
          <v-icon icon="mdi-download" class="mr-2" />
          Download
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup lang="ts">
/**
 * DownloadDialog Component
 *
 * Modal dialog for configuring and triggering data downloads.
 * Allows users to select:
 * - Data selection (filtered vs all)
 * - File format (CSV vs GeoJSON)
 * - Optional aggregation by geographic boundary
 *
 * @component
 */

import { ref, computed, watch } from "vue";
import { format } from "d3-format";
import { track } from "@/shared/analytics";

// Types
export interface DownloadOptions {
  /** Whether to use filtered data or all data */
  useFiltered: boolean;
  /** File format for export */
  format: "csv" | "geojson";
  /** Optional aggregation layer name */
  aggregateBy: string | null;
}

interface Props {
  /** Names of overlay layers available for aggregation */
  overlayLayerNames?: string[];
  /** Current filtered record count */
  filteredCount?: number;
  /** Total record count (unfiltered) */
  totalCount?: number;
}

const props = withDefaults(defineProps<Props>(), {
  overlayLayerNames: () => [],
  filteredCount: 0,
  totalCount: 0,
});

const emit = defineEmits<{
  download: [options: DownloadOptions];
}>();

// Dialog state
const isOpen = ref(false);
const isDownloading = ref(false);

// Form state
const dataSelection = ref<"filtered" | "all">("filtered");
const fileFormat = ref<"csv" | "geojson">("geojson");
const aggregateBy = ref<string | null>(null);

// Format helper
const formatNumber = (n: number) => format(",.0f")(n);

// Aggregation options for select
const aggregationOptions = computed(() =>
  props.overlayLayerNames.map((name) => ({
    title: name,
    value: name,
  }))
);

// Reset form when dialog closes
watch(isOpen, (open) => {
  if (!open) {
    // Reset after close animation
    setTimeout(() => {
      dataSelection.value = "filtered";
      fileFormat.value = "geojson";
      aggregateBy.value = null;
    }, 200);
  }
});

/**
 * Handle download button click.
 * Emits download event with selected options.
 */
function handleDownload(): void {
  const options: DownloadOptions = {
    useFiltered: dataSelection.value === "filtered",
    format: fileFormat.value,
    aggregateBy: aggregateBy.value,
  };

  // Track data download
  track("data_downloaded", {
    data_selection: dataSelection.value,
    format: fileFormat.value,
    aggregate_by: aggregateBy.value,
    record_count:
      dataSelection.value === "filtered"
        ? props.filteredCount
        : props.totalCount,
  });

  emit("download", options);
  isOpen.value = false;
}
</script>

<style scoped>
/* Force dark overlay for dialog */
.download-dialog :deep(.v-overlay__scrim) {
  background-color: rgba(0, 0, 0, 0.5) !important;
  opacity: 1 !important;
}

.download-card {
  background: #2d3339 !important;
  border-radius: 12px !important;
  overflow: hidden;
}

.download-card__title {
  display: flex;
  align-items: center;
  padding: 20px 24px;
  font-size: 1.35rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  background: rgba(0, 0, 0, 0.2);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.download-card__content {
  padding: 28px 24px !important;
}

.option-group {
  margin-bottom: 28px;
}

.option-group:last-child {
  margin-bottom: 0;
}

.option-group__label {
  font-size: 0.95rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.9);
  margin-bottom: 14px;
  letter-spacing: 0.01em;
}

.option-group__optional {
  font-weight: 400;
  color: rgba(255, 255, 255, 0.45);
  margin-left: 6px;
  font-size: 0.85rem;
}

.option-toggle {
  width: 100%;
  display: flex;
  gap: 0;
}

.option-toggle :deep(.v-btn) {
  flex: 1;
  text-transform: none;
  letter-spacing: normal;
  font-size: 0.95rem;
  font-weight: 500;
  height: 48px;
  border-color: rgba(255, 255, 255, 0.2);
  background: rgba(0, 0, 0, 0.15);
}

.option-toggle :deep(.v-btn:first-child) {
  border-radius: 8px 0 0 8px;
}

.option-toggle :deep(.v-btn:last-child) {
  border-radius: 0 8px 8px 0;
}

.option-toggle :deep(.v-btn--active) {
  background: rgba(var(--v-theme-primary), 0.2);
  border-color: rgb(var(--v-theme-primary));
  color: rgb(var(--v-theme-primary));
}

.option-toggle :deep(.v-btn .v-icon) {
  opacity: 0.8;
}

.option-toggle :deep(.v-btn--active .v-icon) {
  opacity: 1;
}

.option-hint {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.55);
  margin-top: 10px;
  line-height: 1.5;
}

.aggregate-select {
  margin-top: 4px;
}

.aggregate-select :deep(.v-field) {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 8px;
  font-size: 0.95rem;
}

.aggregate-select :deep(.v-field__outline) {
  --v-field-border-opacity: 0.2;
}

.aggregate-select :deep(.v-field--focused .v-field__outline) {
  --v-field-border-opacity: 1;
}

.download-card__actions {
  padding: 16px 20px;
  background: rgba(0, 0, 0, 0.1);
}

.download-card__actions :deep(.v-btn) {
  text-transform: none;
  letter-spacing: normal;
  font-weight: 500;
  padding: 0 24px;
}

.download-card__actions :deep(.v-btn--variant-elevated) {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

.download-card__actions :deep(.v-btn--variant-elevated:hover) {
  background: #7a8a9a !important;
}
</style>
