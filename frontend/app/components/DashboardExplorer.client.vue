<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref,
  shallowRef,
  watch,
} from "vue";

import CivicRangeField from "../../layers/civic-ui/app/components/CivicRangeField.vue";
import CivicSelectField from "../../layers/civic-ui/app/components/CivicSelectField.vue";
import DashboardAddressSearch from "./DashboardAddressSearch.vue";
import DashboardCategoryCharts from "./DashboardCategoryCharts.vue";
import DashboardCheckboxFilter from "./DashboardCheckboxFilter.vue";
import DashboardDownloadPanel from "./DashboardDownloadPanel.vue";
import DashboardFilterPanel from "./DashboardFilterPanel.vue";
import DashboardPointMap from "./DashboardPointMap.client.vue";
import DashboardRangeFilter from "./DashboardRangeFilter.vue";
import type { AddressResult } from "~/utils/geocoding";
import {
  DEFAULT_MAP_LAYERS,
  formatMapLayersParam,
  getBoundaryMapLayer,
  getToggleableMapLayers,
  type BoundaryMapLayerId,
  type MapLayerId,
  type ToggleableMapLayerId,
} from "~/utils/mapLayers";
import { BOUNDARY_OVERLAYS } from "~/utils/mapOverlays";
import type { MapView } from "~/utils/mapView";
import {
  createShootingFilterState,
  filterShootingRows,
  hasActiveShootingFilters,
  RACE_VALUES,
  SEX_VALUES,
  shootingHistogram,
  WEEKDAY_VALUES,
  type NumericRange,
  type ShootingCategoryDimension,
  type ShootingFilterState,
  type ShootingRangeDimension,
} from "~/utils/shootingFilters";
import {
  loadShootingRecords,
  summarizeShootingRecords,
  type ShootingRecordResult,
} from "~/utils/shootingRecords";

const props = defineProps<{
  initialView: MapView;
  layers: MapLayerId[];
  year: number | null;
}>();

const emit = defineEmits<{
  summary: [
    value: {
      fatal: number;
      mapped: number;
      nonfatal: number;
      total: number;
    } | null,
  ];
}>();

const route = useRoute();
const router = useRouter();

const sexItems = [
  { label: "Male", value: SEX_VALUES[0] },
  { label: "Female", value: SEX_VALUES[1] },
];
const raceItems = [
  { label: "White (Non-Hispanic)", value: RACE_VALUES[0] },
  { label: "Black (Non-Hispanic)", value: RACE_VALUES[1] },
  { label: "Hispanic (Black or White)", value: RACE_VALUES[2] },
  { label: "Asian", value: RACE_VALUES[3] },
  { label: "Other/Unknown", value: RACE_VALUES[4] },
];
const weekdayItems = [
  { label: "Sunday", value: WEEKDAY_VALUES[0] },
  { label: "Monday", value: WEEKDAY_VALUES[1] },
  { label: "Tuesday", value: WEEKDAY_VALUES[2] },
  { label: "Wednesday", value: WEEKDAY_VALUES[3] },
  { label: "Thursday", value: WEEKDAY_VALUES[4] },
  { label: "Friday", value: WEEKDAY_VALUES[5] },
  { label: "Saturday", value: WEEKDAY_VALUES[6] },
];
const mapLayerItems = [
  { label: "Point locations", value: "point-locations" },
  { label: "Heat map", value: "heat-map" },
  {
    label: "Hot spots by street block",
    value: "hot-spots-by-street-block",
  },
];
const boundaryLayerOptions = BOUNDARY_OVERLAYS.map(({ id, label }) => ({
  label,
  value: id,
}));

const { apiBaseUrl: configuredApiBaseUrl } = useRuntimeConfig().public;
const apiBaseUrl = String(configuredApiBaseUrl).replace(/\/$/, "");
const state = ref<"loading" | "ready" | "error">("loading");
const records = shallowRef<ShootingRecordResult | null>(null);
const defaults = shallowRef<ShootingFilterState | null>(null);
const filters = ref<ShootingFilterState | null>(null);
const boundaryOpacity = ref(0.5);
const savedToggleableLayers = ref<ToggleableMapLayerId[]>([
  ...DEFAULT_MAP_LAYERS,
]);
const searchLocation = shallowRef<AddressResult | null>(null);
const searchResetKey = ref(0);
let requestController: AbortController | null = null;
let requestTimer: ReturnType<typeof setTimeout> | null = null;
let searchTimer: ReturnType<typeof setTimeout> | null = null;
let loadId = 0;

const boundaryLayer = computed(() => getBoundaryMapLayer(props.layers));
const selectedToggleableLayers = computed(() => {
  const selected = getToggleableMapLayers(props.layers);
  return boundaryLayer.value ? savedToggleableLayers.value : selected;
});

const filteredRows = computed(() => {
  if (!records.value || !filters.value) return [];
  return filterShootingRows(records.value.rows, filters.value);
});

const filteredRecords = computed(() =>
  summarizeShootingRecords(filteredRows.value),
);
const yearLabel = computed(() => props.year ?? "all years");
const missingLocationCount = computed(
  () =>
    filteredRecords.value.recordCount -
    filteredRecords.value.points.features.length,
);

const filtersActive = computed(() =>
  filters.value && defaults.value
    ? hasActiveShootingFilters(filters.value, defaults.value)
    : false,
);

function histogram(dimension: ShootingRangeDimension) {
  if (!records.value || !filters.value) return [];
  return shootingHistogram(records.value.rows, filters.value, dimension);
}

const timeHistogram = computed(() => histogram("timeInMs"));
const dateHistogram = computed(() => histogram("dateInMs"));
const ageHistogram = computed(() => histogram("age"));

function cloneFilters(value: ShootingFilterState): ShootingFilterState {
  return {
    ...value,
    age: [...value.age],
    dateInMs: [...value.dateInMs],
    race: [...value.race],
    sex: [...value.sex],
    timeInMs: [...value.timeInMs],
    weekday: [...value.weekday],
  };
}

function categoryIsModified(
  current: Array<number | string>,
  initial: Array<number | string>,
): boolean {
  return (
    current.length !== initial.length ||
    current.some((value, index) => value !== initial[index])
  );
}

function rangeIsModified(
  current: NumericRange,
  initial: NumericRange,
  extra = false,
): boolean {
  return current[0] !== initial[0] || current[1] !== initial[1] || extra;
}

function cancelRequest(): void {
  if (requestTimer) clearTimeout(requestTimer);
  requestTimer = null;
  requestController?.abort();
  requestController = null;
}

async function load(): Promise<void> {
  const currentLoadId = ++loadId;
  cancelRequest();
  state.value = "loading";
  emit("summary", null);
  records.value = null;
  defaults.value = null;
  filters.value = null;

  const controller = new AbortController();
  requestController = controller;
  let timedOut = false;
  requestTimer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, props.year === null ? 30_000 : 15_000);

  try {
    const loaded = await loadShootingRecords(apiBaseUrl, props.year, {
      signal: controller.signal,
    });
    if (currentLoadId !== loadId || timedOut) return;

    const initialFilters = createShootingFilterState(loaded.rows);
    records.value = loaded;
    defaults.value = initialFilters;
    filters.value = cloneFilters(initialFilters);
    state.value = "ready";
  } catch (error) {
    if (
      currentLoadId === loadId &&
      (timedOut || (error as { name?: string } | null)?.name !== "AbortError")
    ) {
      state.value = "error";
    }
  } finally {
    if (currentLoadId === loadId) {
      if (requestTimer) clearTimeout(requestTimer);
      requestTimer = null;
      requestController = null;
    }
  }
}

function updateRange(
  dimension: ShootingRangeDimension,
  value: NumericRange,
): void {
  if (!filters.value) return;
  filters.value = { ...filters.value, [dimension]: value };
}

function updateExcludeUnknownAge(value: boolean): void {
  if (!filters.value) return;
  filters.value = { ...filters.value, excludeUnknownAge: value };
}

function updateBooleanFilter(
  filter: "fatalOnly" | "hasCourtCase",
  event: Event,
): void {
  if (!filters.value) return;
  filters.value = {
    ...filters.value,
    [filter]: (event.target as HTMLInputElement).checked,
  };
}

function updateCategory(
  dimension: ShootingCategoryDimension,
  values: Array<number | string>,
): void {
  if (!filters.value) return;
  filters.value = {
    ...filters.value,
    [dimension]: values,
  } as ShootingFilterState;
}

function resetFilter(dimension: ShootingRangeDimension): void {
  if (!filters.value || !defaults.value) return;
  filters.value = {
    ...filters.value,
    [dimension]: [...defaults.value[dimension]],
    ...(dimension === "age" ? { excludeUnknownAge: false } : {}),
  };
}

function resetCategory(dimension: ShootingCategoryDimension): void {
  if (!filters.value || !defaults.value) return;
  filters.value = {
    ...filters.value,
    [dimension]: [...defaults.value[dimension]],
  };
}

function resetAllFilters(): void {
  if (!defaults.value) return;
  filters.value = cloneFilters(defaults.value);
}

function replaceMapLayers(next: MapLayerId[]): void {
  const value = formatMapLayersParam(next);
  const isDefault = value === formatMapLayersParam(DEFAULT_MAP_LAYERS);
  void router.replace({
    query: {
      ...route.query,
      layers: isDefault ? undefined : value,
    },
  });
}

function updateMapLayers(values: Array<number | string>): void {
  const next = mapLayerItems
    .map((item) => item.value as ToggleableMapLayerId)
    .filter((value) => values.includes(value));
  savedToggleableLayers.value = next;
  if (!boundaryLayer.value) replaceMapLayers(next);
}

function selectOnlyMapLayer(value: number | string): void {
  const layer = value as ToggleableMapLayerId;
  savedToggleableLayers.value = [layer];
  replaceMapLayers([layer]);
}

function formatBoundaryOpacity(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function updateBoundaryLayer(value: string): void {
  if (value) {
    const current = getToggleableMapLayers(props.layers);
    if (current.length > 0) savedToggleableLayers.value = current;
    replaceMapLayers([value as BoundaryMapLayerId]);
    return;
  }
  replaceMapLayers(savedToggleableLayers.value);
}

function handleAddressSelect(result: AddressResult): void {
  if (searchTimer) clearTimeout(searchTimer);
  searchLocation.value = result;
  searchTimer = setTimeout(() => {
    searchLocation.value = null;
    searchResetKey.value += 1;
    searchTimer = null;
  }, 10_000);
}

function clearAddress(): void {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = null;
  searchLocation.value = null;
}

watch(
  [filteredRecords, state],
  ([summary, currentState]) => {
    if (currentState !== "ready") return;
    emit("summary", {
      fatal: summary.fatalRecordCount,
      mapped: summary.points.features.length,
      nonfatal: summary.nonfatalRecordCount,
      total: summary.recordCount,
    });
  },
  { immediate: true },
);

onMounted(load);

onBeforeUnmount(() => {
  loadId += 1;
  cancelRequest();
  if (searchTimer) clearTimeout(searchTimer);
});
</script>

<template>
  <div class="civic-dashboard-browser-explorer" :aria-busy="state === 'loading'">
    <div
      v-if="state === 'loading'"
      class="civic-legacy-explorer-state"
      role="status"
      aria-live="polite"
    >
      Loading {{ yearLabel }} record filters and locations…
    </div>

    <div
      v-else-if="state === 'error'"
      class="civic-legacy-explorer-state"
      role="status"
      aria-live="polite"
    >
      <strong>Detailed records are temporarily unavailable.</strong>
      <button class="usa-button" type="button" @click="load">Try again</button>
    </div>

    <template v-else-if="records && defaults && filters">
      <div class="civic-legacy-map-explorer">
        <div class="civic-legacy-map-view">
          <DashboardPointMap
            :api-base-url="apiBaseUrl"
            :boundary-opacity="boundaryOpacity"
            :fatal-only="filters.fatalOnly"
            :initial-view="initialView"
            :layers="layers"
            :records="filteredRecords"
            :search-location="searchLocation"
            :year="year"
          />
          <div class="civic-legacy-address-search">
            <DashboardAddressSearch
              :reset-key="searchResetKey"
              @clear="clearAddress"
              @select="handleAddressSelect"
            />
          </div>
        </div>

        <aside
          id="filters"
          class="civic-legacy-sidebar"
          aria-label="Map filters and controls"
          tabindex="-1"
        >
          <div class="civic-legacy-sidebar__header">
            <p class="civic-legacy-sidebar__count" aria-live="polite">
              Showing locations for
              <span>
                {{ filteredRecords.points.features.length.toLocaleString() }}
              </span>
              shooting victim{{
                filteredRecords.points.features.length === 1 ? "" : "s"
              }}
            </p>
            <p
              class="civic-legacy-sidebar__note"
              :class="{
                'civic-legacy-sidebar__note--empty': missingLocationCount === 0,
              }"
              :aria-hidden="missingLocationCount === 0 ? 'true' : undefined"
            >
              Note: {{ missingLocationCount.toLocaleString() }} victim{{
                missingLocationCount === 1 ? "" : "s"
              }}
              not shown due to missing locations
            </p>
            <div class="civic-legacy-sidebar__actions">
              <DashboardDownloadPanel
                :all-rows="records.rows"
                :api-base-url="apiBaseUrl"
                :filtered-rows="filteredRows"
              />
              <button
                class="civic-legacy-action-button"
                type="button"
                :disabled="!filtersActive"
                @click="resetAllFilters"
              >
                <svg aria-hidden="true" viewBox="0 0 24 24">
                  <path
                    d="M12 6v3l4-4-4-4v3c-4.42 0-8 3.58-8 8 0 1.57.46 3.03 1.24 4.26L6.7 14.8A5.87 5.87 0 0 1 6 12c0-3.31 2.69-6 6-6zm6.76 1.74L17.3 9.2c.44.84.7 1.79.7 2.8 0 3.31-2.69 6-6 6v-3l-4 4 4 4v-3c4.42 0 8-3.58 8-8 0-1.57-.46-3.03-1.24-4.26z"
                  />
                </svg>
                Reset All Filters
              </button>
            </div>
          </div>

          <div class="civic-legacy-sidebar__scroll">
            <section
              class="civic-legacy-sidebar__section"
              aria-labelledby="map-layers-heading"
            >
              <h2 id="map-layers-heading">Map Layers</h2>
              <div class="civic-legacy-sidebar__rule"></div>
              <DashboardCheckboxFilter
                id="dashboard-map-layer"
                label="Map layers"
                :default-values="DEFAULT_MAP_LAYERS"
                :disabled="boundaryLayer !== null"
                :items="mapLayerItems"
                :only-disabled="false"
                :resettable="false"
                :selected-values="selectedToggleableLayers"
                @select-only="selectOnlyMapLayer"
                @update:selected-values="updateMapLayers"
              />
              <div
                class="civic-dashboard-boundary-control civic-dashboard-boundary-control--compact"
              >
                <CivicSelectField
                  id="dashboard-boundary-layer"
                  clearable
                  floating-label
                  label="Choropleth Layer"
                  tone="inverse"
                  :model-value="boundaryLayer ?? ''"
                  :options="boundaryLayerOptions"
                  hint="Choose a geography to aggregate the data by"
                  @update:model-value="updateBoundaryLayer"
                />
                <CivicRangeField
                  v-if="boundaryLayer"
                  id="dashboard-boundary-opacity"
                  v-model="boundaryOpacity"
                  density="compact"
                  label="Opacity"
                  :min="0"
                  :max="0.5"
                  :step="0.01"
                  :format-value="formatBoundaryOpacity"
                  tone="inverse"
                />
              </div>
            </section>

            <section
              class="civic-legacy-sidebar__section"
              aria-labelledby="record-filters-heading"
            >
              <h2 id="record-filters-heading">Filters</h2>
              <div class="civic-legacy-sidebar__rule"></div>

              <div class="civic-legacy-switches">
                <div class="usa-checkbox">
                  <input
                    id="dashboard-fatal-filter"
                    class="usa-checkbox__input"
                    type="checkbox"
                    :checked="filters.fatalOnly"
                    @change="updateBooleanFilter('fatalOnly', $event)"
                  />
                  <label class="usa-checkbox__label" for="dashboard-fatal-filter">
                    Fatal shootings only
                  </label>
                </div>
                <div class="usa-checkbox">
                  <input
                    id="dashboard-court-filter"
                    class="usa-checkbox__input"
                    type="checkbox"
                    :checked="filters.hasCourtCase"
                    @change="updateBooleanFilter('hasCourtCase', $event)"
                  />
                  <label class="usa-checkbox__label" for="dashboard-court-filter">
                    Has public court record
                  </label>
                </div>
              </div>

              <DashboardFilterPanel
                title="Gender"
                :modified="categoryIsModified(filters.sex, defaults.sex)"
                @reset="resetCategory('sex')"
              >
                <DashboardCheckboxFilter
                  id="dashboard-gender-filter"
                  label="Gender"
                  :default-values="defaults.sex"
                  :items="sexItems"
                  :resettable="false"
                  :selected-values="filters.sex"
                  @select-only="updateCategory('sex', [$event])"
                  @update:selected-values="updateCategory('sex', $event)"
                />
              </DashboardFilterPanel>
              <DashboardFilterPanel
                title="Race/Ethnicity"
                :modified="categoryIsModified(filters.race, defaults.race)"
                @reset="resetCategory('race')"
              >
                <DashboardCheckboxFilter
                  id="dashboard-race-filter"
                  label="Race/Ethnicity"
                  :default-values="defaults.race"
                  :items="raceItems"
                  :resettable="false"
                  :selected-values="filters.race"
                  @select-only="updateCategory('race', [$event])"
                  @update:selected-values="updateCategory('race', $event)"
                />
              </DashboardFilterPanel>
              <DashboardFilterPanel
                title="Day of Week"
                :modified="categoryIsModified(filters.weekday, defaults.weekday)"
                @reset="resetCategory('weekday')"
              >
                <DashboardCheckboxFilter
                  id="dashboard-weekday-filter"
                  :columns="2"
                  label="Day of Week"
                  :default-values="defaults.weekday"
                  :items="weekdayItems"
                  :resettable="false"
                  :selected-values="filters.weekday"
                  @select-only="updateCategory('weekday', [$event])"
                  @update:selected-values="updateCategory('weekday', $event)"
                />
              </DashboardFilterPanel>
              <DashboardFilterPanel
                title="Time of Day"
                :modified="rangeIsModified(filters.timeInMs, defaults.timeInMs)"
                @reset="resetFilter('timeInMs')"
              >
                <DashboardRangeFilter
                  id="dashboard-time-filter"
                  label="Time of Day"
                  format="time"
                  :bins="timeHistogram"
                  :default-range="defaults.timeInMs"
                  :range="filters.timeInMs"
                  :resettable="false"
                  :step="60_000"
                  @update:range="updateRange('timeInMs', $event)"
                />
              </DashboardFilterPanel>
              <DashboardFilterPanel
                title="Date"
                :modified="rangeIsModified(filters.dateInMs, defaults.dateInMs)"
                @reset="resetFilter('dateInMs')"
              >
                <DashboardRangeFilter
                  id="dashboard-date-filter"
                  label="Date"
                  format="date"
                  :include-year="year === null"
                  :bins="dateHistogram"
                  :default-range="defaults.dateInMs"
                  :range="filters.dateInMs"
                  :resettable="false"
                  :step="86_400_000"
                  @update:range="updateRange('dateInMs', $event)"
                />
              </DashboardFilterPanel>
              <DashboardFilterPanel
                title="Age"
                :modified="rangeIsModified(filters.age, defaults.age, filters.excludeUnknownAge)"
                @reset="resetFilter('age')"
              >
                <DashboardRangeFilter
                  id="dashboard-age-filter"
                  label="Age"
                  format="age"
                  :bins="ageHistogram"
                  :default-range="defaults.age"
                  :exclude-missing="filters.excludeUnknownAge"
                  :range="filters.age"
                  :resettable="false"
                  :step="1"
                  show-exclude-missing
                  @update:exclude-missing="updateExcludeUnknownAge"
                  @update:range="updateRange('age', $event)"
                />
              </DashboardFilterPanel>
            </section>
          </div>
        </aside>
      </div>
    </template>

    <DashboardCategoryCharts :rows="filteredRows" :state="state" />
  </div>
</template>
