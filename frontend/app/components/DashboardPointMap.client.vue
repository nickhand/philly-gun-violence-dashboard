<script setup lang="ts">
import type { FeatureCollection, Geometry } from "geojson";
import type {
  ExpressionSpecification,
  GeoJSONSource,
  Map as MapLibreMap,
  MapLayerMouseEvent,
  Popup,
  PopupOptions,
  StyleSpecification,
} from "maplibre-gl";
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import mapStyle from "../../src/data/style.json";
import { enhanceBasemapLabels } from "../../src/features/explorer/config/basemapLabels";
import type { AddressResult } from "~/utils/geocoding";
import {
  AGGREGATE_ZERO_COLOR,
  boundaryMapColor,
  createAggregateLegend,
  type AggregateLegendModel,
} from "~/utils/mapLegend";
import {
  DEFAULT_MAP_LAYERS,
  formatMapLayersParam,
  getBoundaryMapLayer,
  type MapLayerId,
} from "~/utils/mapLayers";
import {
  boundaryOverlayConfig,
  CITY_LIMITS_DATASET,
  fetchOverlayFeatureCollection,
  fetchStreetHotSpots,
  joinBoundaryCounts,
  type BoundaryOverlayConfig,
} from "~/utils/mapOverlays";
import {
  DEFAULT_MAP_VIEW,
  formatMapViewParam,
  MAP_MAX_ZOOM,
  MAP_MIN_ZOOM,
  type MapView,
} from "~/utils/mapView";
import {
  type ShootingPointProperties,
  type ShootingRecordResult,
} from "~/utils/shootingRecords";

const props = defineProps<{
  apiBaseUrl: string;
  boundaryOpacity: number;
  fatalOnly: boolean;
  initialView: MapView;
  layers: MapLayerId[];
  records: ShootingRecordResult;
  searchLocation: AddressResult | null;
  year: number | null;
}>();

const route = useRoute();
const router = useRouter();
const mapContainer = ref<HTMLDivElement | null>(null);
const printImage = ref<HTMLImageElement | null>(null);
const printMapImage = ref("");
const printPending = ref(false);
const printError = ref(false);
const state = ref<"loading" | "ready" | "error">("loading");
const mapDataLoading = ref(false);
const mapIdle = ref(false);
const cityState = ref<"idle" | "loading" | "ready" | "error">("idle");
const boundaryState = ref<"idle" | "loading" | "ready" | "error">("idle");
const streetState = ref<"idle" | "loading" | "ready" | "error">("idle");
const boundaryLegendMax = ref(0);
const boundaryRepresentedCount = ref<number | null>(null);
const streetLegendMax = ref(0);
const streetRepresentedCount = ref<number | null>(null);
let loadId = 0;
let boundaryRequestId = 0;
let streetRequestId = 0;
let cityController: AbortController | null = null;
let boundaryController: AbortController | null = null;
let streetController: AbortController | null = null;
let streetTimer: ReturnType<typeof setTimeout> | null = null;
let boundaryCleanup: (() => void) | null = null;
let streetCleanup: (() => void) | null = null;
let cachedBoundary:
  | { id: MapLayerId; data: FeatureCollection<Geometry> }
  | null = null;

interface ActiveMap {
  cleanupInteractions: () => void;
  createPopup: (options: PopupOptions) => Popup;
  instance: MapLibreMap;
  onDataLoading: () => void;
  onIdle: () => void;
  onMoveEnd: () => void;
  pinnedLayerId: string | null;
  pinnedPopup: Popup | null;
  ready: boolean;
  timer: ReturnType<typeof setTimeout> | null;
}

let activeMap: ActiveMap | null = null;

const BASEMAP_ATTRIBUTION =
  "Sources: Esri, HERE, Garmin, FAO, NOAA, USGS, © OpenStreetMap contributors, and the GIS User Community.";
const DATA_ATTRIBUTION =
  "Shooting-victim records: Philadelphia Police Department via OpenDataPhilly.";
const MAP_PRINT_CLASS = "civic-dashboard-map-print-active";
const MOBILE_MAP_BREAKPOINT = 768;

function collapseMobileAttribution(container: HTMLElement | null): void {
  if (window.innerWidth >= MOBILE_MAP_BREAKPOINT) return;

  const attribution = container?.querySelector<HTMLElement>(
    ".maplibregl-ctrl-attrib.maplibregl-compact",
  );
  attribution?.classList.remove(
    "maplibregl-compact-show",
    "mapboxgl-compact-show",
  );
  attribution?.removeAttribute("open");
}

function setMapPrintMode(active: boolean): void {
  document.documentElement.classList.toggle(MAP_PRINT_CLASS, active);
  document.body.classList.toggle(MAP_PRINT_CLASS, active);
}

class HomeControl {
  private button: HTMLButtonElement | null = null;
  private container: HTMLDivElement | null = null;
  private map: MapLibreMap | null = null;

  private readonly resetMap = () => {
    this.map?.flyTo({
      center: DEFAULT_MAP_VIEW.center,
      duration: 1_000,
      zoom: DEFAULT_MAP_VIEW.zoom,
    });
  };

  onAdd(map: MapLibreMap): HTMLElement {
    this.map = map;
    this.container = document.createElement("div");
    this.container.className = "maplibregl-ctrl maplibregl-ctrl-group";

    this.button = document.createElement("button");
    this.button.className = "maplibregl-ctrl-home";
    this.button.type = "button";
    this.button.title = "Reset map view";
    this.button.setAttribute("aria-label", "Reset map view to Philadelphia");
    this.button.innerHTML = `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>`;
    this.button.addEventListener("click", this.resetMap);
    this.container.appendChild(this.button);

    return this.container;
  }

  onRemove(): void {
    this.button?.removeEventListener("click", this.resetMap);
    this.container?.remove();
    this.button = null;
    this.container = null;
    this.map = null;
  }
}

function pointRadiusExpression(year: number | null): ExpressionSpecification {
  return [
    "interpolate",
    ["exponential", 1.25],
    ["zoom"],
    10,
    year === null ? 1 : 3.5,
    16,
    year === null ? 9 : 11,
  ];
}

const mappedCount = computed(() => props.records.points.features.length);
const mappedFatalCount = computed(
  () =>
    props.records.points.features.filter((feature) => feature.properties.fatal)
      .length,
);
const mappedNonfatalCount = computed(
  () => mappedCount.value - mappedFatalCount.value,
);
const recordCount = computed(() => props.records.recordCount);
const yearLabel = computed(() =>
  props.year === null ? "all years" : String(props.year),
);
const printTitle = computed(() =>
  props.year === null
    ? "Philadelphia shooting-victim map — all available years"
    : `Philadelphia shooting-victim map — ${props.year}`,
);
const yearQueryValue = computed(() =>
  props.year === null ? "All Years" : String(props.year),
);
const yearStatusContext = computed(() =>
  props.year === null ? "across all years" : `in ${props.year}`,
);
const boundaryId = computed(() => getBoundaryMapLayer(props.layers));
const boundaryConfig = computed(() =>
  boundaryId.value ? boundaryOverlayConfig(boundaryId.value) : null,
);
const showsStreetHotSpots = computed(() =>
  props.layers.includes("hot-spots-by-street-block"),
);
const isMapLoading = computed(
  () =>
    state.value === "loading" ||
    (state.value === "ready" && !mapIdle.value) ||
    mapDataLoading.value ||
    cityState.value === "loading" ||
    boundaryState.value === "loading" ||
    streetState.value === "loading",
);
const printDisabled = computed(
  () =>
    printPending.value ||
    state.value !== "ready" ||
    isMapLoading.value ||
    (boundaryConfig.value !== null && boundaryState.value !== "ready") ||
    (showsStreetHotSpots.value && streetState.value !== "ready"),
);
const boundaryLegend = computed(() => {
  const config = boundaryConfig.value;
  return config && boundaryLegendMax.value > 0
    ? createAggregateLegend(
        "choropleth",
        boundaryLegendMax.value,
        config.legendUnit,
      )
    : null;
});
const streetLegend = computed(() =>
  streetLegendMax.value > 0
    ? createAggregateLegend(
        "street-hot-spots",
        streetLegendMax.value,
        "street block",
      )
    : null,
);
const aggregateLegends = computed<AggregateLegendModel[]>(() => {
  const legends: AggregateLegendModel[] = [];
  if (boundaryState.value === "ready" && boundaryLegend.value) {
    legends.push(boundaryLegend.value);
  }
  if (
    streetState.value === "ready" &&
    showsStreetHotSpots.value &&
    streetLegend.value
  ) {
    legends.push(streetLegend.value);
  }
  return legends;
});
const recordDescription = computed(() => {
  const qualifier = props.fatalOnly ? "fatal " : "";
  const noun = recordCount.value === 1 ? "record" : "records";
  return `${qualifier}shooting-victim ${noun}`;
});

function omittedRecordsText(
  represented: number,
  reason: string,
  layer: string,
): string {
  const omitted = Math.max(0, recordCount.value - represented);
  if (omitted === 0) return "";
  const noun = omitted === 1 ? "record" : "records";
  const verb = omitted === 1 ? "is" : "are";
  return `${omitted.toLocaleString()} ${noun} ${verb} not shown in ${layer} because ${reason}.`;
}

const pointDisplays = computed(() => {
  const displays: string[] = [];
  if (props.layers.includes("point-locations")) {
    displays.push("point locations");
  }
  if (props.layers.includes("heat-map")) displays.push("density");
  if (displays.length === 0) return "";
  return displays.length === 1 ? displays[0] : `${displays[0]} and ${displays[1]}`;
});

const pointLayerName = computed(() => {
  const point = props.layers.includes("point-locations");
  const heat = props.layers.includes("heat-map");
  if (point && heat) return "the point and density layers";
  return point ? "the point layer" : "the density layer";
});

const mapLabel = computed(() => {
  const config = boundaryConfig.value;
  if (config) {
    if (
      boundaryState.value === "ready" &&
      boundaryRepresentedCount.value !== null
    ) {
      return `Map showing ${boundaryRepresentedCount.value} of ${recordCount.value} ${recordDescription.value} aggregated by ${config.label} in Philadelphia for ${yearLabel.value}`;
    }
    if (boundaryState.value === "error") {
      return `Map of Philadelphia with ${config.label} aggregation unavailable for ${yearLabel.value}`;
    }
    return `Map loading shooting-victim records aggregated by ${config.label} in Philadelphia for ${yearLabel.value}`;
  }
  if (props.layers.length === 0) {
    return `Map of Philadelphia with no shooting data layer selected for ${yearLabel.value}`;
  }
  const qualifier = props.fatalOnly ? " fatal" : "";
  const locations = `${mappedCount.value}${qualifier} shooting-victim ${mappedCount.value === 1 ? "location" : "locations"}`;
  const point = props.layers.includes("point-locations");
  const heat = props.layers.includes("heat-map");
  if ((point || heat) && showsStreetHotSpots.value) {
    const streetPart =
      streetState.value === "ready" && streetRepresentedCount.value !== null
        ? `street-block hot spots for ${streetRepresentedCount.value} of ${recordCount.value} records`
        : "street-block hot spots loading";
    return `Map showing ${pointDisplays.value} for ${locations}, with ${streetPart}, in Philadelphia for ${yearLabel.value}`;
  }
  if (point && heat) {
    return `Map showing point locations and density for ${locations} in Philadelphia for ${yearLabel.value}`;
  }
  if (showsStreetHotSpots.value && !point && !heat) {
    if (
      streetState.value === "ready" &&
      streetRepresentedCount.value !== null
    ) {
      return `Map showing street-block hot spots for ${streetRepresentedCount.value} of ${recordCount.value} ${recordDescription.value} in Philadelphia for ${yearLabel.value}`;
    }
    if (streetState.value === "error") {
      return `Map of Philadelphia with street-block hot spots unavailable for ${yearLabel.value}`;
    }
    return `Map loading street-block hot spots in Philadelphia for ${yearLabel.value}`;
  }
  if (heat && !point) {
    return `Heat map showing the density of ${locations} in Philadelphia for ${yearLabel.value}`;
  }
  return `Map showing ${locations} in Philadelphia for ${yearLabel.value}`;
});

function syncMapCanvasAccessibility(instance = activeMap?.instance): void {
  if (!instance) return;
  const canvas = instance.getCanvas();
  canvas.setAttribute("aria-label", mapLabel.value);
  canvas.setAttribute(
    "aria-describedby",
    "dashboard-point-map-description",
  );
}

const statusText = computed(() => {
  const config = boundaryConfig.value;
  if (config) {
    if (boundaryState.value === "error") {
      return `${config.label} could not be shown for ${recordCount.value.toLocaleString()} ${recordDescription.value} ${yearStatusContext.value}.`;
    }
    if (
      boundaryState.value !== "ready" ||
      boundaryRepresentedCount.value === null
    ) {
      return `Preparing ${recordCount.value.toLocaleString()} ${recordDescription.value} for ${config.label} ${yearStatusContext.value}.`;
    }
    const represented = boundaryRepresentedCount.value;
    return [
      `Showing ${represented.toLocaleString()} of ${recordCount.value.toLocaleString()} ${recordDescription.value} aggregated by ${config.label} ${yearStatusContext.value}.`,
      omittedRecordsText(
        represented,
        `a matching ${config.legendUnit} is unavailable`,
        "this layer",
      ),
    ]
      .filter(Boolean)
      .join(" ");
  }
  if (props.layers.length === 0) {
    return `No shooting data layer is selected. ${recordCount.value.toLocaleString()} ${recordDescription.value} match the current filters ${yearStatusContext.value}.`;
  }

  const messages: string[] = [];
  if (pointDisplays.value) {
    messages.push(
      `Showing ${pointDisplays.value} for ${mappedCount.value.toLocaleString()} of ${recordCount.value.toLocaleString()} ${recordDescription.value} ${yearStatusContext.value}.`,
    );
    messages.push(
      omittedRecordsText(
        mappedCount.value,
        "usable map coordinates are unavailable",
        pointLayerName.value,
      ),
    );
  }
  if (
    showsStreetHotSpots.value &&
    streetState.value === "ready" &&
    streetRepresentedCount.value !== null
  ) {
    const represented = streetRepresentedCount.value;
    messages.push(
      `${pointDisplays.value ? "Street-block hot spots represent" : "Showing street-block hot spots for"} ${represented.toLocaleString()} of ${recordCount.value.toLocaleString()} ${recordDescription.value} ${yearStatusContext.value}.`,
    );
    messages.push(
      omittedRecordsText(
        represented,
        "a matching street block is unavailable",
        "the street-block layer",
      ),
    );
  } else if (showsStreetHotSpots.value && !pointDisplays.value) {
    messages.push(
      streetState.value === "error"
        ? `Street-block hot spots could not be shown for ${recordCount.value.toLocaleString()} ${recordDescription.value} ${yearStatusContext.value}.`
        : `Preparing street-block hot spots for ${recordCount.value.toLocaleString()} ${recordDescription.value} ${yearStatusContext.value}.`,
    );
  }
  return messages.filter(Boolean).join(" ");
});

async function printMap(): Promise<void> {
  const map = activeMap;
  if (!map?.ready || printDisabled.value) return;

  printPending.value = true;
  printError.value = false;
  clearPrintMap();
  try {
    const image = map.instance.getCanvas().toDataURL("image/png");
    if (!image.startsWith("data:image/png") || image.length < 32) {
      throw new Error("The map canvas did not produce a printable image.");
    }
    printMapImage.value = image;
    await nextTick();
    if (typeof printImage.value?.decode === "function") {
      await printImage.value.decode().catch(() => undefined);
    }
    setMapPrintMode(true);
    window.print();
  } catch {
    clearPrintMap();
    printError.value = true;
  } finally {
    printPending.value = false;
  }
}

function clearPrintMap(): void {
  setMapPrintMode(false);
  printMapImage.value = "";
}

function abortOverlayRequests(): void {
  cityController?.abort();
  boundaryController?.abort();
  streetController?.abort();
  cityController = null;
  boundaryController = null;
  streetController = null;
  if (streetTimer) clearTimeout(streetTimer);
  streetTimer = null;
}

function removeLayerAndSource(
  instance: MapLibreMap,
  layerId: string,
  sourceId: string,
): void {
  if (instance.getLayer(layerId)) instance.removeLayer(layerId);
  if (instance.getSource(sourceId)) instance.removeSource(sourceId);
}

function waitForNextMapIdle(target = activeMap): void {
  if (target?.ready) mapIdle.value = false;
}

function beforeDataLayers(instance: MapLibreMap): string | undefined {
  if (instance.getLayer("shooting-record-heat-map")) {
    return "shooting-record-heat-map";
  }
  if (instance.getLayer("shooting-record-points")) {
    return "shooting-record-points";
  }
  if (instance.getLayer("address-search-ring")) {
    return "address-search-ring";
  }
  return undefined;
}

function boundaryFeatureLabel(
  config: BoundaryOverlayConfig,
  properties: Record<string, unknown>,
): string {
  const value = String(properties[config.geoid] ?? "Unknown");
  const prefixes: Partial<Record<MapLayerId, string>> = {
    "police-districts": "Police District #",
    "council-districts": "Council District #",
    "pa-house-districts": "House District #",
    "pa-senate-districts": "Senate District #",
    "zip-codes": "",
    neighborhoods: "",
    "school-catchments": "",
  };
  return `${prefixes[config.id] ?? ""}${value}`;
}

function streetFeatureLabel(properties: Record<string, unknown>): string {
  const street =
    typeof properties.street_name === "string" ? properties.street_name : "";
  const block = properties.block_number;
  return street && (typeof block === "string" || typeof block === "number")
    ? `${block} ${street}`
    : "Street Block";
}

function aggregatePopupContent(
  label: string,
  properties: Record<string, unknown>,
): HTMLElement {
  const root = document.createElement("div");
  root.className = "map-tooltip";

  const title = document.createElement("div");
  title.className = "tooltip-title";
  title.textContent = label;

  const stat = document.createElement("div");
  stat.className = "tooltip-stat";
  const value = document.createElement("span");
  value.className = "tooltip-stat-value";
  value.textContent = (Number(properties.total_shootings) || 0).toLocaleString(
    "en-US",
  );
  const statLabel = document.createElement("span");
  statLabel.className = "tooltip-stat-label";
  statLabel.textContent = "shooting victims";
  stat.append(value, statLabel);
  root.append(title, stat);
  return root;
}

function installAggregateInteractions(
  map: ActiveMap,
  layerId: string,
  label: (properties: Record<string, unknown>) => string,
): () => void {
  const { instance } = map;
  const hoverPopup = map.createPopup({
    className: "map-tooltip-popup",
    closeButton: false,
    closeOnClick: false,
    maxWidth: "320px",
  });

  const popupAt = (event: MapLayerMouseEvent, pinned: boolean): Popup | null => {
    const properties = event.features?.[0]?.properties;
    if (!properties) return null;
    const popup = pinned
      ? map.createPopup({
          className: "map-tooltip-popup map-tooltip-popup--pinned",
          closeButton: true,
          closeOnClick: false,
          maxWidth: "320px",
        })
      : hoverPopup;
    return popup
      .setLngLat(event.lngLat)
      .setDOMContent(aggregatePopupContent(label(properties), properties))
      .addTo(instance);
  };

  const onMove = (event: MapLayerMouseEvent) => {
    if (map.pinnedPopup && map.pinnedLayerId === layerId) return;
    popupAt(event, false);
  };
  const onClick = (event: MapLayerMouseEvent) => {
    if (!event.features?.[0]?.properties) return;
    hoverPopup.remove();
    map.pinnedPopup?.remove();
    map.pinnedPopup = popupAt(event, true);
    map.pinnedLayerId = map.pinnedPopup ? layerId : null;
    const currentPopup = map.pinnedPopup;
    currentPopup?.on("close", () => {
      if (map.pinnedPopup === currentPopup) {
        map.pinnedPopup = null;
        map.pinnedLayerId = null;
      }
    });
  };
  const onLeave = () => {
    hoverPopup.remove();
  };
  instance.on("click", layerId, onClick);
  instance.on("mousemove", layerId, onMove);
  instance.on("mouseleave", layerId, onLeave);
  return () => {
    hoverPopup.remove();
    if (map.pinnedLayerId === layerId) {
      map.pinnedPopup?.remove();
      map.pinnedPopup = null;
      map.pinnedLayerId = null;
    }
    instance.off("click", layerId, onClick);
    instance.off("mousemove", layerId, onMove);
    instance.off("mouseleave", layerId, onLeave);
  };
}

function destroyMap(target = activeMap): void {
  if (!target) return;
  abortOverlayRequests();
  if (target.timer) clearTimeout(target.timer);
  target.cleanupInteractions();
  boundaryCleanup?.();
  streetCleanup?.();
  boundaryCleanup = null;
  streetCleanup = null;
  target.instance.off("dataloading", target.onDataLoading);
  target.instance.off("idle", target.onIdle);
  target.instance.off("moveend", target.onMoveEnd);
  target.instance.remove();
  mapDataLoading.value = false;
  mapIdle.value = false;
  cityState.value = "idle";
  if (activeMap === target) activeMap = null;
}

function readSelectedRecord(
  event: MapLayerMouseEvent,
): ShootingPointProperties | null {
  const properties = event.features?.[0]?.properties;
  if (!properties || typeof properties.fatal !== "boolean") return null;
  const numberOrNull = (value: unknown) =>
    typeof value === "number" && Number.isFinite(value) ? value : null;
  const textOrNull = (value: unknown) =>
    typeof value === "string" && value.trim() ? value : null;
  return {
    age: numberOrNull(properties.age),
    date: textOrNull(properties.date),
    dcKey: textOrNull(properties.dcKey),
    fatal: properties.fatal,
    hasCourtCase:
      typeof properties.hasCourtCase === "boolean"
        ? properties.hasCourtCase
        : null,
    race: textOrNull(properties.race),
    sex: textOrNull(properties.sex),
    streetBlock: textOrNull(properties.streetBlock),
    timeInMs: numberOrNull(properties.timeInMs),
  };
}

function formatTime(timeInMs: number): string {
  const totalMinutes = Math.floor(timeInMs / 60_000);
  const hours = Math.floor(totalMinutes / 60) % 24;
  const minutes = totalMinutes % 60;
  const hour = hours % 12 || 12;
  return `${hour}:${String(minutes).padStart(2, "0")} ${hours >= 12 ? "PM" : "AM"}`;
}

function formatTooltipDate(date: string): string {
  return new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
    weekday: "short",
    year: "numeric",
  }).format(new Date(`${date}T00:00:00Z`));
}

function formatTooltipLocation(streetBlock: string): string {
  return streetBlock.replace(/^(\d+) block of (.+)$/i, "$1 $2");
}

function pointPopupContent(record: ShootingPointProperties): HTMLElement {
  const root = document.createElement("div");
  root.className = "civic-map-tooltip";
  root.setAttribute("aria-label", "Shooting incident details");

  const badge = document.createElement("span");
  badge.className = record.fatal
    ? "civic-map-tooltip__badge civic-map-tooltip__badge--fatal"
    : "civic-map-tooltip__badge civic-map-tooltip__badge--nonfatal";
  badge.textContent = record.fatal ? "Fatal" : "Nonfatal";
  root.appendChild(badge);

  const title = document.createElement("div");
  title.className = "civic-map-tooltip__title";
  title.textContent = "Shooting Incident";
  root.appendChild(title);

  const addRow = (label: string, value: string | null) => {
    if (!value) return;
    const row = document.createElement("div");
    row.className = "civic-map-tooltip__row";
    const labelElement = document.createElement("span");
    labelElement.className = "civic-map-tooltip__label";
    const valueElement = document.createElement("span");
    valueElement.className = "civic-map-tooltip__value";
    labelElement.textContent = label;
    valueElement.textContent = value;
    row.append(labelElement, valueElement);
    root.appendChild(row);
  };
  const addSection = (label: string) => {
    const divider = document.createElement("div");
    divider.className = "civic-map-tooltip__divider";
    const heading = document.createElement("div");
    heading.className = "civic-map-tooltip__section-heading";
    heading.textContent = label;
    root.append(divider, heading);
  };

  addRow("Date", record.date ? formatTooltipDate(record.date) : null);
  addRow("Time", record.timeInMs === null ? null : formatTime(record.timeInMs));
  addRow(
    "Location",
    record.streetBlock ? formatTooltipLocation(record.streetBlock) : null,
  );

  addSection("Victim Information");
  addRow("Age", record.age === null ? null : `${record.age} years old`);
  addRow(
    "Race/Ethnicity",
    record.race === "B"
      ? "Black (Non-Hispanic)"
      : record.race === "W"
        ? "White (Non-Hispanic)"
        : record.race === "H"
          ? "Hispanic"
          : record.race === "A"
            ? "Asian"
            : record.race,
  );
  addRow(
    "Gender",
    record.sex === "M" ? "Male" : record.sex === "F" ? "Female" : record.sex,
  );

  addSection("Case Information");
  addRow("DC Number", record.dcKey);
  addRow(
    "Court Case",
    record.hasCourtCase === null ? null : record.hasCourtCase ? "Yes" : "No",
  );
  return root;
}

async function installCityBoundary(
  target: ActiveMap,
  currentLoadId: number,
): Promise<void> {
  cityState.value = "loading";
  const controller = new AbortController();
  cityController = controller;
  try {
    const data = await fetchOverlayFeatureCollection(
      props.apiBaseUrl,
      `/boundaries/${CITY_LIMITS_DATASET}`,
      { signal: controller.signal },
    );
    if (
      controller.signal.aborted ||
      activeMap !== target ||
      currentLoadId !== loadId
    ) {
      return;
    }
    waitForNextMapIdle(target);
    target.instance.addSource("city-limits", { type: "geojson", data });
    target.instance.addLayer({
      id: "city-limits-line",
      type: "line",
      source: "city-limits",
      paint: {
        "line-color": "#ffffff",
        "line-opacity": 0.9,
        "line-width": 3,
      },
    });
    cityState.value = "ready";
  } catch (error) {
    if (
      activeMap === target &&
      currentLoadId === loadId &&
      (error as { name?: string } | null)?.name !== "AbortError"
    ) {
      cityState.value = "error";
      // The basemap and record layers remain useful if the reference outline
      // is temporarily unavailable.
    }
  } finally {
    if (cityController === controller) cityController = null;
  }
}

async function syncBoundaryOverlay(): Promise<void> {
  const requestId = ++boundaryRequestId;
  boundaryController?.abort();
  boundaryController = null;
  const map = activeMap;
  const config = boundaryConfig.value;
  if (!map?.ready) return;

  if (!config) {
    boundaryCleanup?.();
    boundaryCleanup = null;
    if (
      map.instance.getLayer("shooting-boundary-fill") ||
      map.instance.getSource("shooting-boundary")
    ) {
      waitForNextMapIdle(map);
    }
    removeLayerAndSource(
      map.instance,
      "shooting-boundary-fill",
      "shooting-boundary",
    );
    boundaryLegendMax.value = 0;
    boundaryRepresentedCount.value = null;
    boundaryState.value = "idle";
    return;
  }

  boundaryState.value = "loading";
  boundaryLegendMax.value = 0;
  boundaryRepresentedCount.value = null;
  const controller = new AbortController();
  boundaryController = controller;
  try {
    let raw: FeatureCollection<Geometry>;
    if (cachedBoundary?.id === config.id) {
      raw = cachedBoundary.data;
    } else {
      raw = await fetchOverlayFeatureCollection(
        props.apiBaseUrl,
        `/boundaries/${config.dataset}`,
        { signal: controller.signal },
      );
      cachedBoundary = { id: config.id, data: raw };
    }
    if (
      requestId !== boundaryRequestId ||
      controller.signal.aborted ||
      activeMap !== map
    ) {
      return;
    }

    const counted = joinBoundaryCounts(raw, props.records.rows, config);
    boundaryLegendMax.value = counted.maxCount;
    boundaryRepresentedCount.value = counted.representedCount;
    const data = {
      type: "FeatureCollection" as const,
      features: counted.features,
    };
    waitForNextMapIdle(map);
    const source = map.instance.getSource("shooting-boundary") as
      | GeoJSONSource
      | undefined;
    if (source) {
      source.setData(data);
    } else {
      map.instance.addSource("shooting-boundary", { type: "geojson", data });
      map.instance.addLayer(
        {
          id: "shooting-boundary-fill",
          type: "fill",
          source: "shooting-boundary",
          paint: {
            "fill-color": boundaryLegend.value
              ? boundaryMapColor(boundaryLegend.value)
              : AGGREGATE_ZERO_COLOR,
            "fill-opacity": props.boundaryOpacity,
            "fill-outline-color": "#dfe1e2",
          },
        },
        beforeDataLayers(map.instance),
      );
    }
    map.instance.setPaintProperty(
      "shooting-boundary-fill",
      "fill-color",
      boundaryLegend.value
        ? boundaryMapColor(boundaryLegend.value)
        : AGGREGATE_ZERO_COLOR,
    );
    map.instance.setPaintProperty(
      "shooting-boundary-fill",
      "fill-opacity",
      props.boundaryOpacity,
    );
    boundaryCleanup?.();
    boundaryCleanup = installAggregateInteractions(
      map,
      "shooting-boundary-fill",
      (properties) => boundaryFeatureLabel(config, properties),
    );
    boundaryState.value = "ready";
  } catch (error) {
    if (
      requestId === boundaryRequestId &&
      (error as { name?: string } | null)?.name !== "AbortError"
    ) {
      boundaryLegendMax.value = 0;
      boundaryRepresentedCount.value = null;
      boundaryState.value = "error";
    }
  } finally {
    if (boundaryController === controller) boundaryController = null;
  }
}

async function syncStreetHotSpots(): Promise<void> {
  const requestId = ++streetRequestId;
  streetController?.abort();
  streetController = null;
  const map = activeMap;
  if (!map?.ready) return;

  if (!showsStreetHotSpots.value) {
    streetCleanup?.();
    streetCleanup = null;
    if (
      map.instance.getLayer("shooting-street-hot-spots") ||
      map.instance.getSource("shooting-streets")
    ) {
      waitForNextMapIdle(map);
    }
    removeLayerAndSource(
      map.instance,
      "shooting-street-hot-spots",
      "shooting-streets",
    );
    streetLegendMax.value = 0;
    streetRepresentedCount.value = null;
    streetState.value = "idle";
    return;
  }

  streetState.value = "loading";
  streetLegendMax.value = 0;
  streetRepresentedCount.value = null;
  const controller = new AbortController();
  streetController = controller;
  try {
    const counted = await fetchStreetHotSpots(
      props.apiBaseUrl,
      props.records.rows,
      { signal: controller.signal },
    );
    if (
      requestId !== streetRequestId ||
      controller.signal.aborted ||
      activeMap !== map
    ) {
      return;
    }
    const data = {
      type: "FeatureCollection" as const,
      features: counted.features,
    };
    streetLegendMax.value = counted.maxCount;
    streetRepresentedCount.value = counted.representedCount;
    waitForNextMapIdle(map);
    const source = map.instance.getSource("shooting-streets") as
      | GeoJSONSource
      | undefined;
    if (source) {
      source.setData(data);
    } else {
      map.instance.addSource("shooting-streets", { type: "geojson", data });
      map.instance.addLayer(
        {
          id: "shooting-street-hot-spots",
          type: "line",
          source: "shooting-streets",
          paint: {
            "line-color": streetLegend.value?.mapColor ?? AGGREGATE_ZERO_COLOR,
            "line-opacity": 0.9,
            "line-width": [
              "interpolate",
              ["linear"],
              ["zoom"],
              10,
              2,
              13,
              5,
            ],
          },
        },
        beforeDataLayers(map.instance),
      );
      streetCleanup = installAggregateInteractions(
        map,
        "shooting-street-hot-spots",
        streetFeatureLabel,
      );
    }
    map.instance.setPaintProperty(
      "shooting-street-hot-spots",
      "line-color",
      streetLegend.value?.mapColor ?? AGGREGATE_ZERO_COLOR,
    );
    streetState.value = "ready";
  } catch (error) {
    if (
      requestId === streetRequestId &&
      (error as { name?: string } | null)?.name !== "AbortError"
    ) {
      streetLegendMax.value = 0;
      streetRepresentedCount.value = null;
      streetState.value = "error";
    }
  } finally {
    if (streetController === controller) streetController = null;
  }
}

function scheduleStreetHotSpots(): void {
  if (streetTimer) clearTimeout(streetTimer);
  if (!showsStreetHotSpots.value) {
    streetTimer = null;
    void syncStreetHotSpots();
    return;
  }
  streetState.value = "loading";
  streetRepresentedCount.value = null;
  streetTimer = setTimeout(() => {
    streetTimer = null;
    void syncStreetHotSpots();
  }, 200);
}

function installSearchLocation(instance: MapLibreMap): void {
  instance.addSource("address-search-location", {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  instance.addLayer({
    id: "address-search-ring",
    type: "circle",
    source: "address-search-location",
    paint: {
      "circle-color": "rgba(0,0,0,0)",
      "circle-radius": 13,
      "circle-stroke-color": "#73b3e7",
      "circle-stroke-width": 3,
    },
  });
  instance.addLayer({
    id: "address-search-center",
    type: "circle",
    source: "address-search-location",
    paint: {
      "circle-color": "#73b3e7",
      "circle-radius": 3.5,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1,
    },
  });
}

function syncSearchLocation(fly = true): void {
  const map = activeMap;
  if (!map?.ready) return;
  const location = props.searchLocation;
  const source = map.instance.getSource("address-search-location") as
    | GeoJSONSource
    | undefined;
  waitForNextMapIdle(map);
  source?.setData({
    type: "FeatureCollection",
    features: location
      ? [
          {
            type: "Feature",
            geometry: { type: "Point", coordinates: [location.lon, location.lat] },
            properties: {},
          },
        ]
      : [],
  });
  if (location && fly) {
    map.instance.flyTo({
      center: [location.lon, location.lat],
      duration: 1_500,
      zoom: 16,
    });
  }
}

async function initializeMap(currentLoadId: number): Promise<void> {
  let candidate: ActiveMap | null = null;

  try {
    await import("maplibre-gl/dist/maplibre-gl.css");
    const { default: maplibregl } = await import("maplibre-gl");
    if (currentLoadId !== loadId || !mapContainer.value) return;

    const instance = new maplibregl.Map({
      container: mapContainer.value,
      style: mapStyle as StyleSpecification,
      center: props.initialView.center,
      zoom: props.initialView.zoom,
      minZoom: MAP_MIN_ZOOM,
      maxZoom: MAP_MAX_ZOOM,
      dragRotate: false,
      pitchWithRotate: false,
      attributionControl: false,
      preserveDrawingBuffer: true,
    });
    syncMapCanvasAccessibility(instance);
    const onMoveEnd = () => {
      const center = instance.getCenter();
      const map = formatMapViewParam({
        center: [center.lng, center.lat],
        zoom: instance.getZoom(),
      });
      const query = {
        ...route.query,
        year: yearQueryValue.value,
        layers:
          formatMapLayersParam(props.layers) ===
          formatMapLayersParam(DEFAULT_MAP_LAYERS)
            ? undefined
            : formatMapLayersParam(props.layers),
        map,
      };

      if (
        route.query.year === query.year &&
        route.query.layers === query.layers &&
        route.query.map === query.map
      ) {
        return;
      }

      void router.replace({ query });
    };
    const onDataLoading = () => {
      if (activeMap === candidate && currentLoadId === loadId) {
        mapDataLoading.value = true;
        mapIdle.value = false;
      }
    };
    const onIdle = () => {
      if (activeMap === candidate && currentLoadId === loadId) {
        mapDataLoading.value = false;
        mapIdle.value = true;
      }
    };
    candidate = {
      cleanupInteractions: () => {},
      createPopup: (options) => new maplibregl.Popup(options),
      instance,
      onDataLoading,
      onIdle,
      onMoveEnd,
      pinnedLayerId: null,
      pinnedPopup: null,
      ready: false,
      timer: null,
    };
    activeMap = candidate;
    instance.on("dataloading", onDataLoading);
    instance.on("idle", onIdle);

    instance.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "top-right",
    );
    instance.addControl(new HomeControl(), "top-right");
    instance.addControl(new maplibregl.ScaleControl(), "bottom-left");
    const compactAttribution = window.innerWidth < MOBILE_MAP_BREAKPOINT;
    instance.addControl(
      new maplibregl.AttributionControl({ compact: compactAttribution }),
      "bottom-right",
    );
    collapseMobileAttribution(mapContainer.value);

    candidate.timer = setTimeout(() => {
      if (
        activeMap === candidate &&
        currentLoadId === loadId &&
        !candidate.ready
      ) {
        state.value = "error";
        destroyMap(candidate);
      }
    }, 15_000);

    instance.once("load", () => {
      if (activeMap !== candidate || currentLoadId !== loadId) return;

      try {
        // MapLibre expands a newly compacted attribution control. Collapse it
        // after style attribution has loaded so it starts as an info button.
        collapseMobileAttribution(mapContainer.value);
        enhanceBasemapLabels(instance);
        instance.addSource("shooting-records", {
          type: "geojson",
          data: props.records.points,
        });
        instance.addLayer({
            id: "shooting-record-heat-map",
            type: "heatmap",
            source: "shooting-records",
            layout: {
              visibility: props.layers.includes("heat-map") ? "visible" : "none",
            },
            paint: {
              "heatmap-color": [
                "interpolate",
                ["linear"],
                ["heatmap-density"],
                0,
                "rgba(0, 0, 0, 0)",
                0.1,
                "#120d31",
                0.2,
                "#331067",
                0.3,
                "#59157e",
                0.4,
                "#7e2482",
                0.5,
                "#a3307e",
                0.6,
                "#c83e73",
                0.7,
                "#e95462",
                0.8,
                "#fa7d5e",
                0.9,
                "#fea973",
                1,
                "#fed395",
              ],
              "heatmap-intensity": [
                "interpolate",
                ["linear"],
                ["zoom"],
                11,
                1,
                15,
                5,
              ],
              "heatmap-opacity": [
                "interpolate",
                ["linear"],
                ["zoom"],
                12,
                0.9,
                17,
                0.5,
              ],
              "heatmap-radius": [
                "interpolate",
                ["exponential", 1.5],
                ["zoom"],
                10,
                15,
                15,
                50,
              ],
              "heatmap-weight": 1,
            },
          });
        instance.addLayer({
            id: "shooting-record-points",
            type: "circle",
            source: "shooting-records",
            layout: {
              visibility: props.layers.includes("point-locations")
                ? "visible"
                : "none",
            },
            paint: {
              "circle-radius": pointRadiusExpression(props.year),
              "circle-color": [
                "case",
                ["boolean", ["get", "fatal"], false],
                "#ff8a8a",
                "#e5dc8e",
              ],
              "circle-opacity": 0.7,
              "circle-stroke-color": [
                "case",
                ["boolean", ["get", "fatal"], false],
                "#d84545",
                "#d3c913",
              ],
              "circle-stroke-width": 1,
            },
          });
          const pointLayerId = "shooting-record-points";
          let hoverPopup: InstanceType<typeof maplibregl.Popup> | null = null;
          const popupAt = (
            event: MapLayerMouseEvent,
            pinned: boolean,
          ): InstanceType<typeof maplibregl.Popup> | null => {
            const record = readSelectedRecord(event);
            if (!record) return null;
            return new maplibregl.Popup({
              className: pinned
                ? "civic-dashboard-point-popup civic-dashboard-point-popup--pinned"
                : "civic-dashboard-point-popup",
              closeButton: pinned,
              closeOnClick: false,
              focusAfterOpen: false,
              maxWidth: "320px",
            })
              .setLngLat(event.lngLat)
              .setDOMContent(pointPopupContent(record))
              .addTo(instance);
          };
          const onPointClick = (event: MapLayerMouseEvent) => {
            hoverPopup?.remove();
            hoverPopup = null;
            candidate.pinnedPopup?.remove();
            candidate.pinnedPopup = popupAt(event, true);
            candidate.pinnedLayerId = candidate.pinnedPopup
              ? pointLayerId
              : null;
            const currentPopup = candidate.pinnedPopup;
            currentPopup?.on("close", () => {
              if (candidate.pinnedPopup === currentPopup) {
                candidate.pinnedPopup = null;
                candidate.pinnedLayerId = null;
              }
            });
          };
          const onPointEnter = (event: MapLayerMouseEvent) => {
            instance.getCanvas().style.cursor = "pointer";
            if (
              candidate.pinnedPopup &&
              candidate.pinnedLayerId === pointLayerId
            ) {
              return;
            }
            hoverPopup?.remove();
            hoverPopup = popupAt(event, false);
          };
          const onPointLeave = () => {
            instance.getCanvas().style.cursor = "";
            hoverPopup?.remove();
            hoverPopup = null;
          };
          instance.on("click", pointLayerId, onPointClick);
          instance.on("mouseenter", pointLayerId, onPointEnter);
          instance.on("mouseleave", pointLayerId, onPointLeave);
          candidate.cleanupInteractions = () => {
            hoverPopup?.remove();
            if (candidate.pinnedLayerId === pointLayerId) {
              candidate.pinnedPopup?.remove();
              candidate.pinnedPopup = null;
              candidate.pinnedLayerId = null;
            }
            instance.off("click", pointLayerId, onPointClick);
            instance.off("mouseenter", pointLayerId, onPointEnter);
            instance.off("mouseleave", pointLayerId, onPointLeave);
          };
        installSearchLocation(instance);
        if (candidate.timer) clearTimeout(candidate.timer);
        candidate.timer = null;
        candidate.ready = true;
        instance.on("moveend", onMoveEnd);
        syncMapCanvasAccessibility(instance);
        syncSearchLocation();
        void installCityBoundary(candidate, currentLoadId);
        void syncBoundaryOverlay();
        scheduleStreetHotSpots();
        state.value = "ready";
      } catch {
        state.value = "error";
        destroyMap(candidate);
      }
    });
  } catch {
    if (candidate) destroyMap(candidate);
    if (currentLoadId === loadId) state.value = "error";
  }
}

async function initialize(): Promise<void> {
  const currentLoadId = ++loadId;
  destroyMap();
  mapDataLoading.value = false;
  mapIdle.value = false;
  cityState.value = "idle";
  boundaryState.value = "idle";
  streetState.value = "idle";
  boundaryRepresentedCount.value = null;
  streetRepresentedCount.value = null;
  state.value = "loading";
  await initializeMap(currentLoadId);
}

function syncPrimaryLayerVisibility(): void {
  const map = activeMap;
  if (!map?.ready) return;
  const layers = [
    ["shooting-record-points", props.layers.includes("point-locations")],
    ["shooting-record-heat-map", props.layers.includes("heat-map")],
  ] as const;
  const changes = layers.filter(([id, visible]) => {
    if (!map.instance.getLayer(id)) return false;
    return (
      map.instance.getLayoutProperty(id, "visibility") !==
      (visible ? "visible" : "none")
    );
  });
  if (changes.length === 0) return;

  waitForNextMapIdle(map);
  for (const [id, visible] of changes) {
    map.instance.setLayoutProperty(
      id,
      "visibility",
      visible ? "visible" : "none",
    );
  }
}

watch(
  () => props.records,
  (records) => {
    const map = activeMap;
    if (!map?.ready) return;
    waitForNextMapIdle(map);
    const source = map.instance.getSource("shooting-records") as
      | GeoJSONSource
      | undefined;
    source?.setData(records.points);
    void syncBoundaryOverlay();
    scheduleStreetHotSpots();
  },
);

watch(boundaryId, () => {
  void syncBoundaryOverlay();
});

watch(showsStreetHotSpots, () => {
  scheduleStreetHotSpots();
});

watch(
  () => formatMapLayersParam(props.layers),
  () => {
    syncPrimaryLayerVisibility();
  },
);

watch(
  () => props.boundaryOpacity,
  (opacity) => {
    const map = activeMap;
    if (map?.ready && map.instance.getLayer("shooting-boundary-fill")) {
      waitForNextMapIdle(map);
      map.instance.setPaintProperty(
        "shooting-boundary-fill",
        "fill-opacity",
        opacity,
      );
    }
  },
);

watch(
  () => props.searchLocation,
  () => syncSearchLocation(),
);

watch(
  () => props.year,
  (year) => {
    const map = activeMap;
    if (map?.ready && map.instance.getLayer("shooting-record-points")) {
      waitForNextMapIdle(map);
      map.instance.setPaintProperty(
        "shooting-record-points",
        "circle-radius",
        pointRadiusExpression(year),
      );
    }
  },
);

watch(mapLabel, () => {
  syncMapCanvasAccessibility();
});

watch(
  () => [
    props.initialView.center[0],
    props.initialView.center[1],
    props.initialView.zoom,
  ] as const,
  ([longitude, latitude, zoom]) => {
    const map = activeMap;
    if (!map?.ready) return;

    const center = map.instance.getCenter();
    if (
      Math.abs(center.lng - longitude) < 0.000_001 &&
      Math.abs(center.lat - latitude) < 0.000_001 &&
      Math.abs(map.instance.getZoom() - zoom) < 0.001
    ) {
      return;
    }

    waitForNextMapIdle(map);
    map.instance.jumpTo({ center: [longitude, latitude], zoom });
  },
);

onMounted(() => {
  window.addEventListener("afterprint", clearPrintMap);
  initialize();
});

onBeforeUnmount(() => {
  window.removeEventListener("afterprint", clearPrintMap);
  clearPrintMap();
  loadId += 1;
  destroyMap();
});
</script>

<template>
  <div
    class="civic-dashboard-point-map"
    :class="`civic-dashboard-point-map--${state}`"
  >
    <div
      id="dashboard-point-map-description"
      class="civic-dashboard-point-map__status"
      aria-live="polite"
    >
      <p v-if="state === 'loading'">
        <template v-if="year === null">
          Loading shooting-victim locations for all years…
        </template>
        <template v-else>Loading {{ year }} shooting-victim locations…</template>
      </p>
      <template v-else-if="state === 'error'">
        <p>The interactive map is temporarily unavailable.</p>
        <button class="usa-button" type="button" @click="initialize">
          Try again
        </button>
      </template>
      <template v-else>
        <p>
          {{ statusText }}
          <template v-if="layers.includes('point-locations')">
            Select a point marker to see its date and nearest-street context.
          </template>
        </p>
        <p v-if="boundaryState === 'loading'">
          Loading {{ boundaryConfig?.label }}…
        </p>
        <p v-else-if="boundaryState === 'error'">
          The selected geographic aggregation is temporarily unavailable.
        </p>
        <p v-if="streetState === 'loading'">Loading street-block hot spots…</p>
        <p v-else-if="streetState === 'error'">
          Street-block hot spots are temporarily unavailable.
        </p>
        <p v-if="searchLocation">
          Centered on {{ searchLocation.shortName }}. The location marker clears
          after 10 seconds.
        </p>
      </template>
    </div>

    <div class="civic-dashboard-point-map__frame" :aria-busy="isMapLoading">
      <div
        ref="mapContainer"
        class="civic-dashboard-point-map__canvas"
        :aria-hidden="state !== 'ready'"
        :inert="state !== 'ready'"
      ></div>
      <div
        v-if="isMapLoading"
        class="civic-dashboard-map-loading"
        role="progressbar"
        aria-label="Loading map data"
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <svg aria-hidden="true" viewBox="0 0 44 44">
          <circle
            class="civic-dashboard-map-loading__track"
            cx="22"
            cy="22"
            r="20"
          />
          <circle
            class="civic-dashboard-map-loading__indicator"
            cx="22"
            cy="22"
            r="20"
          />
        </svg>
      </div>
      <div v-if="state === 'ready'" class="civic-dashboard-map-print-control">
        <button
          class="civic-dashboard-map-print-button"
          type="button"
          :disabled="printDisabled"
          @click="printMap"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24">
            <path
              d="M6 9V3h12v6h1a3 3 0 0 1 3 3v5h-4v4H6v-4H2v-5a3 3 0 0 1 3-3zm2-4v4h8V5zm0 10v4h8v-4zm10-1h2v-2a1 1 0 0 0-1-1h-1z"
            />
          </svg>
          <span>{{ printPending ? "Preparing…" : "Print map" }}</span>
        </button>
        <p v-if="printError" role="status">
          The map could not be prepared for printing.
        </p>
      </div>
      <div
        v-if="aggregateLegends.length > 0"
        class="civic-dashboard-map-legends"
      >
        <div
          v-for="legend in aggregateLegends"
          :key="legend.id"
          class="civic-dashboard-map-legend"
          role="img"
          :aria-label="legend.accessibleLabel"
          :data-map-legend="legend.id"
          :data-map-legend-scale="legend.scale"
        >
          <div class="civic-dashboard-map-legend__label">
            Map legend
            <span>{{ legend.title }}</span>
          </div>
          <div class="civic-dashboard-map-legend__scale" aria-hidden="true">
            <div
              v-if="legend.zeroColor"
              class="civic-dashboard-map-legend__zero"
              data-map-legend-zero
            >
              <span
                class="civic-dashboard-map-legend__zero-swatch"
                :style="{ backgroundColor: legend.zeroColor }"
              ></span>
              <span data-map-legend-min="empty">0</span>
            </div>
            <div class="civic-dashboard-map-legend__range">
              <div
                class="civic-dashboard-map-legend__bar"
                :style="legend.barStyle"
                data-map-legend-bar
              ></div>
              <div
                class="civic-dashboard-map-legend__ticks"
              >
                <span
                  v-for="(tick, tickIndex) in legend.ticks"
                  :key="tick.value"
                  data-map-legend-tick
                  :data-map-legend-min="tickIndex === 0 ? 'range' : undefined"
                  :data-map-legend-mid="
                    tickIndex > 0 && tickIndex < legend.ticks.length - 1
                      ? ''
                      : undefined
                  "
                  :data-map-legend-max="
                    !legend.singleValue && tickIndex === legend.ticks.length - 1
                      ? ''
                      : undefined
                  "
                  :data-value="tick.value"
                  :class="{
                    'civic-dashboard-map-legend__tick--first':
                      !legend.singleValue && tickIndex === 0,
                    'civic-dashboard-map-legend__tick--last':
                      !legend.singleValue &&
                      tickIndex === legend.ticks.length - 1,
                  }"
                  :style="{ left: `${tick.position * 100}%` }"
                >
                  {{ tick.label }}
                </span>
              </div>
            </div>
          </div>
          <div class="civic-dashboard-map-legend__key" aria-hidden="true">
            <span v-if="legend.zeroColor && legend.zeroLabel">
              Gray: {{ legend.zeroLabel.toLowerCase() }}.{{ " " }}
            </span>
            <span v-if="legend.singleValue">1 shooting victim.{{ " " }}</span>
            <span v-else>{{ legend.direction }}{{ " " }}</span>
            <span>{{ legend.note }}</span>
          </div>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <section
        v-if="printMapImage"
        class="civic-dashboard-map-print-sheet"
        aria-label="Printable map"
      >
        <header>
          <p>Philadelphia Gun Violence Dashboard</p>
          <h1>{{ printTitle }}</h1>
          <p>{{ statusText }}</p>
        </header>
        <img
          ref="printImage"
          :src="printMapImage"
          :alt="mapLabel"
        />
        <div class="civic-dashboard-map-print-sheet__legend">
          <ul v-if="layers.includes('point-locations')">
            <li>
              <span class="civic-dashboard-map-print-sheet__marker--fatal"></span>
              Fatal — {{ mappedFatalCount.toLocaleString() }}
            </li>
            <li>
              <span class="civic-dashboard-map-print-sheet__marker--nonfatal"></span>
              Nonfatal — {{ mappedNonfatalCount.toLocaleString() }}
            </li>
          </ul>
          <p v-if="layers.includes('heat-map')">
            Density: brighter areas indicate a greater concentration of mapped
            records.
          </p>
          <div
            v-for="legend in aggregateLegends"
            :key="legend.id"
            class="civic-dashboard-map-legend civic-dashboard-map-legend--print"
            role="img"
            :aria-label="legend.accessibleLabel"
            :data-map-legend="legend.id"
            :data-map-legend-scale="legend.scale"
          >
            <div class="civic-dashboard-map-legend__label">
              Map legend
              <span>{{ legend.title }}</span>
            </div>
            <div class="civic-dashboard-map-legend__scale" aria-hidden="true">
              <div
                v-if="legend.zeroColor"
                class="civic-dashboard-map-legend__zero"
                data-map-legend-zero
              >
                <span
                  class="civic-dashboard-map-legend__zero-swatch"
                  :style="{ backgroundColor: legend.zeroColor }"
                ></span>
                <span data-map-legend-min="empty">0</span>
              </div>
              <div class="civic-dashboard-map-legend__range">
                <div
                  class="civic-dashboard-map-legend__bar"
                  :style="legend.barStyle"
                  data-map-legend-bar
                ></div>
                <div
                  class="civic-dashboard-map-legend__ticks"
                >
                  <span
                    v-for="(tick, tickIndex) in legend.ticks"
                    :key="tick.value"
                    data-map-legend-tick
                    :data-map-legend-min="
                      tickIndex === 0 ? 'range' : undefined
                    "
                    :data-map-legend-mid="
                      tickIndex > 0 && tickIndex < legend.ticks.length - 1
                        ? ''
                        : undefined
                    "
                    :data-map-legend-max="
                      !legend.singleValue &&
                      tickIndex === legend.ticks.length - 1
                        ? ''
                        : undefined
                    "
                    :data-value="tick.value"
                    :class="{
                      'civic-dashboard-map-legend__tick--first':
                        !legend.singleValue && tickIndex === 0,
                      'civic-dashboard-map-legend__tick--last':
                        !legend.singleValue &&
                        tickIndex === legend.ticks.length - 1,
                    }"
                    :style="{ left: `${tick.position * 100}%` }"
                  >
                    {{ tick.label }}
                  </span>
                </div>
              </div>
            </div>
            <div class="civic-dashboard-map-legend__key" aria-hidden="true">
              <span v-if="legend.zeroColor && legend.zeroLabel">
                Gray: {{ legend.zeroLabel.toLowerCase() }}.{{ " " }}
              </span>
              <span v-if="legend.singleValue">1 shooting victim.{{ " " }}</span>
              <span v-else>{{ legend.direction }}{{ " " }}</span>
              <span>{{ legend.note }}</span>
            </div>
          </div>
        </div>
        <footer>
          <p>{{ DATA_ATTRIBUTION }}</p>
          <p>{{ BASEMAP_ATTRIBUTION }}</p>
        </footer>
      </section>
    </Teleport>

  </div>
</template>

<style scoped>
:deep(.maplibregl-map) {
  font-family: "Public Sans Web", "Public Sans", system-ui, sans-serif;
}

.civic-dashboard-map-loading {
  position: absolute;
  z-index: 10;
  top: 150px;
  right: 10px;
  width: 32px;
  height: 32px;
  color: #ffffff;
  pointer-events: none;
}

.civic-dashboard-map-loading svg {
  display: block;
  width: 100%;
  height: 100%;
  animation: civic-map-loading-rotate 1.4s linear infinite;
}

.civic-dashboard-map-loading circle {
  fill: none;
  stroke: currentcolor;
  stroke-width: 4;
  transform-origin: center;
}

.civic-dashboard-map-loading__track {
  opacity: 0.12;
}

.civic-dashboard-map-loading__indicator {
  stroke-linecap: round;
  animation: civic-map-loading-dash 1.4s ease-in-out infinite;
}

@keyframes civic-map-loading-rotate {
  to {
    transform: rotate(360deg);
  }
}

@keyframes civic-map-loading-dash {
  0% {
    stroke-dasharray: 1, 200;
    stroke-dashoffset: 0;
  }

  50% {
    stroke-dasharray: 90, 200;
    stroke-dashoffset: -35;
  }

  100% {
    stroke-dasharray: 90, 200;
    stroke-dashoffset: -124;
  }
}

.civic-dashboard-map-print-control {
  position: absolute;
  z-index: 7;
  top: 10px;
  right: 49px;
  max-width: 11rem;
}

.civic-dashboard-map-print-button {
  display: flex;
  min-height: 34px;
  padding: 0.4rem 0.65rem;
  align-items: center;
  gap: 0.4rem;
  border: 1px solid #667178;
  border-radius: 4px;
  color: #172126;
  background: #ffffff;
  cursor: pointer;
  font-size: 0.78rem;
  font-weight: 400;
  line-height: 1;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.18);
}

.civic-dashboard-map-print-button:not(:disabled):hover {
  background: #f0f0f0;
}

.civic-dashboard-map-print-button:disabled {
  cursor: wait;
  opacity: 0.72;
}

.civic-dashboard-map-print-button svg {
  width: 1rem;
  height: 1rem;
  flex: 0 0 auto;
  fill: currentColor;
}

.civic-dashboard-map-print-control p {
  margin: 0.35rem 0 0;
  padding: 0.35rem;
  color: #ffffff;
  background: rgba(29, 34, 36, 0.94);
  font-size: 0.72rem;
  line-height: 1.35;
}

.civic-dashboard-map-print-sheet {
  display: none;
}

@media (max-width: 35.99em) {
  .civic-dashboard-map-print-control {
    top: 117px;
    right: 10px;
  }

  .civic-dashboard-map-print-button {
    box-sizing: border-box;
    width: 29px;
    height: 29px;
    min-height: 29px;
    padding: 0;
    justify-content: center;
  }

  .civic-dashboard-map-print-button svg {
    width: 20px;
    height: 20px;
  }

  .civic-dashboard-map-print-button span {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    border: 0;
    margin: -1px;
    clip: rect(0, 0, 0, 0);
    clip-path: inset(50%);
    overflow: hidden;
    white-space: nowrap;
  }
}

@media (prefers-reduced-motion: reduce) {
  .civic-dashboard-map-loading svg,
  .civic-dashboard-map-loading__indicator {
    animation-duration: 0.01ms;
    animation-iteration-count: 1;
  }
}

:deep(.maplibregl-canvas:focus-visible) {
  outline-offset: -0.25rem !important;
}

:deep(.maplibregl-ctrl-attrib-button:focus),
:deep(.maplibregl-ctrl-group button:focus) {
  box-shadow: none !important;
}

:deep(.maplibregl-ctrl-attrib) {
  color: #ffffff;
  background: rgba(50, 50, 50, 0.8);
  font-size: 10px;
}

:deep(.maplibregl-ctrl-attrib a) {
  color: #b8ddf5;
}

@media screen and (max-width: 47.99em) {
  :deep(.maplibregl-ctrl-attrib.maplibregl-compact) {
    box-sizing: content-box;
    max-width: calc(100% - 20px);
    min-height: 24px;
    padding: 0 24px 0 0;
    border-radius: 12px;
    color: #172126;
    background: #ffffff;
    line-height: 1.35;
  }

  :deep(.maplibregl-ctrl-attrib.maplibregl-compact-show) {
    padding: 4px 32px 4px 8px;
    border-radius: 4px;
  }

  :deep(.maplibregl-ctrl-attrib.maplibregl-compact a) {
    color: #005ea8;
  }
}

:deep(.maplibregl-ctrl-scale) {
  color: #ffffff;
  background: rgba(50, 50, 50, 0.8);
  border-color: #ffffff;
  font-size: 10px;
}

:deep(.maplibregl-ctrl-home) {
  display: flex;
  width: 29px;
  height: 29px;
  padding: 0;
  align-items: center;
  justify-content: center;
  color: #333333;
  background: #ffffff;
  border: 0;
  border-radius: 4px;
  cursor: pointer;
}

:deep(.maplibregl-ctrl-home:hover) {
  background: #f0f0f0;
}

:deep(.maplibregl-ctrl-home svg) {
  display: block;
}

:deep(.civic-dashboard-point-popup .maplibregl-popup-content) {
  padding: 12px 14px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: #ffffff;
  background: rgba(30, 30, 30, 0.95);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(8px);
  pointer-events: none;
}

:deep(.civic-dashboard-point-popup--pinned .maplibregl-popup-content) {
  border-color: rgba(100, 149, 237, 0.5);
  cursor: text;
  pointer-events: auto;
  user-select: text;
}

:deep(.civic-dashboard-point-popup .maplibregl-popup-tip) {
  border-top-color: rgba(30, 30, 30, 0.95);
}

:deep(.civic-dashboard-point-popup--pinned .maplibregl-popup-close-button) {
  top: 2px;
  right: 2px;
  padding: 4px 8px;
  border: 0;
  color: rgba(255, 255, 255, 0.7);
  background: transparent;
  font-size: 20px;
  line-height: 1;
  transition: color 0.15s ease;
}

:deep(.civic-dashboard-point-popup--pinned .maplibregl-popup-close-button:hover) {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
}

:deep(.civic-map-tooltip) {
  min-width: 180px;
  max-width: 280px;
  color: #ffffff;
  font-family:
    -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 13px;
  line-height: 1.4;
}

:deep(.civic-dashboard-point-popup:not(.civic-dashboard-point-popup--pinned) .civic-map-tooltip::after) {
  display: block;
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.5);
  content: "Click to pin";
  font-size: 10px;
  text-align: center;
}

:deep(.civic-map-tooltip__title) {
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.15);
  color: #ffffff;
  font-size: 14px;
  font-weight: 600;
}

:deep(.civic-map-tooltip__badge) {
  display: inline-block;
  margin-bottom: 6px;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

:deep(.civic-map-tooltip__badge--fatal) {
  color: #ffffff;
  background: rgba(216, 69, 69, 0.9);
}

:deep(.civic-map-tooltip__badge--nonfatal) {
  color: #333333;
  background: rgba(229, 220, 142, 0.9);
}

:deep(.civic-map-tooltip__row) {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 3px 0;
}

:deep(.civic-map-tooltip__label) {
  flex-shrink: 0;
  color: rgba(255, 255, 255, 0.7);
  font-size: 12px;
}

:deep(.civic-map-tooltip__value) {
  color: #ffffff;
  font-size: 12px;
  font-weight: 500;
  text-align: right;
}

:deep(.civic-map-tooltip__divider) {
  height: 1px;
  margin: 8px 0;
  background: rgba(255, 255, 255, 0.15);
}

:deep(.civic-map-tooltip__section-heading) {
  margin: 4px 0 6px;
  color: rgba(255, 255, 255, 0.6);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

:deep(.map-tooltip-popup .maplibregl-popup-content) {
  padding: 12px 14px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  background: rgba(30, 30, 30, 0.95);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(8px);
  pointer-events: none;
}

:deep(.map-tooltip-popup--pinned .maplibregl-popup-content) {
  border-color: rgba(100, 149, 237, 0.5);
  cursor: text;
  pointer-events: auto;
  user-select: text;
}

:deep(.map-tooltip-popup--pinned .map-tooltip),
:deep(.map-tooltip-popup--pinned .map-tooltip *) {
  user-select: text;
  -webkit-user-select: text;
}

:deep(.map-tooltip-popup--pinned .maplibregl-popup-close-button) {
  top: 2px;
  right: 2px;
  padding: 4px 8px;
  border: 0;
  color: rgba(255, 255, 255, 0.7);
  background: transparent;
  font-size: 20px;
  line-height: 1;
  transition: color 0.15s ease;
}

:deep(.map-tooltip-popup--pinned .maplibregl-popup-close-button:hover) {
  border-radius: 4px;
  color: #ffffff;
  background: rgba(255, 255, 255, 0.1);
}

:deep(.map-tooltip-popup:not(.map-tooltip-popup--pinned) .map-tooltip::after) {
  display: block;
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.5);
  content: "Click to pin";
  font-size: 10px;
  text-align: center;
}

:deep(.map-tooltip-popup .maplibregl-popup-tip) {
  border-top-color: rgba(30, 30, 30, 0.95);
}

:deep(.map-tooltip) {
  min-width: 180px;
  max-width: 280px;
  color: #ffffff;
  font-family:
    -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 13px;
  line-height: 1.4;
}

:deep(.tooltip-title) {
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.15);
  color: #ffffff;
  font-size: 14px;
  font-weight: 600;
}

:deep(.tooltip-stat) {
  display: flex;
  padding: 8px 0;
  flex-direction: column;
  align-items: center;
}

:deep(.tooltip-stat-value) {
  color: #ffffff;
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
}

:deep(.tooltip-stat-label) {
  margin-top: 4px;
  color: rgba(255, 255, 255, 0.6);
  font-size: 11px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.civic-dashboard-map-legends {
  position: absolute;
  z-index: 7;
  bottom: 50px;
  left: 10px;
  display: grid;
  gap: 0.5rem;
}

.civic-dashboard-map-legend {
  box-sizing: border-box;
  width: 220px;
  padding: 8px 12px;
  border: 2px solid rgba(122, 181, 229, 0.4);
  border-radius: 6px;
  color: #ffffff;
  background: rgba(40, 46, 51, 0.97);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.4);
}

.civic-dashboard-map-legend__label {
  margin-bottom: 6px;
  color: rgba(255, 255, 255, 0.7);
  font-size: 11px;
  font-weight: 400;
  letter-spacing: 0.04em;
  line-height: 1.2;
  text-transform: uppercase;
}

.civic-dashboard-map-legend__label span {
  display: block;
  margin-top: 2px;
  color: #ffffff;
  letter-spacing: 0;
  text-transform: none;
}

.civic-dashboard-map-legend__scale {
  display: flex;
  min-width: 0;
  gap: 7px;
  align-items: start;
}

.civic-dashboard-map-legend__zero {
  display: grid;
  flex: 0 0 14px;
  gap: 4px;
  justify-items: center;
  color: rgba(255, 255, 255, 0.85);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.civic-dashboard-map-legend__zero-swatch {
  display: block;
  width: 14px;
  height: 8px;
  border: 1px solid rgba(255, 255, 255, 0.55);
  border-radius: 2px;
}

.civic-dashboard-map-legend__range {
  min-width: 0;
  flex: 1 1 auto;
}

.civic-dashboard-map-legend__bar {
  width: 100%;
  height: 8px;
  border-radius: 3px;
}

.civic-dashboard-map-legend__ticks {
  position: relative;
  height: 13px;
  margin-top: 4px;
  color: rgba(255, 255, 255, 0.85);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  font-weight: 400;
  line-height: 1.2;
}

.civic-dashboard-map-legend__ticks span {
  position: absolute;
  top: 0;
  white-space: nowrap;
  transform: translateX(-50%);
}

.civic-dashboard-map-legend__tick--first {
  transform: none !important;
}

.civic-dashboard-map-legend__tick--last {
  transform: translateX(-100%) !important;
}

.civic-dashboard-map-legend__key {
  display: grid;
  margin-top: 6px;
  color: rgba(255, 255, 255, 0.72);
  font-size: 10px;
  font-weight: 400;
  line-height: 1.3;
}

.civic-dashboard-map-legend--print {
  position: static;
  width: 220px;
  padding: 0;
  border: 0;
  border-radius: 0;
  color: #11181c;
  background: transparent;
  box-shadow: none;
}

.civic-dashboard-map-legend--print .civic-dashboard-map-legend__label {
  color: #565c65;
  font-size: 7.5pt;
}

.civic-dashboard-map-legend--print .civic-dashboard-map-legend__label span {
  color: #11181c;
}

.civic-dashboard-map-legend--print .civic-dashboard-map-legend__zero,
.civic-dashboard-map-legend--print .civic-dashboard-map-legend__ticks {
  color: #11181c;
  font-size: 7.5pt;
}

.civic-dashboard-map-legend--print .civic-dashboard-map-legend__key {
  color: #3d4551;
  font-size: 7pt;
}

.civic-dashboard-map-legend--print
  .civic-dashboard-map-legend__zero-swatch {
  border-color: #565c65;
}
</style>
