export const TOGGLEABLE_MAP_LAYERS = [
  "point-locations",
  "heat-map",
  "hot-spots-by-street-block",
] as const;

export const BOUNDARY_MAP_LAYERS = [
  "police-districts",
  "council-districts",
  "zip-codes",
  "neighborhoods",
  "pa-house-districts",
  "pa-senate-districts",
  "school-catchments",
] as const;

export type ToggleableMapLayerId = (typeof TOGGLEABLE_MAP_LAYERS)[number];
export type BoundaryMapLayerId = (typeof BOUNDARY_MAP_LAYERS)[number];
export type MapLayerId = ToggleableMapLayerId | BoundaryMapLayerId;

export const DEFAULT_MAP_LAYERS: MapLayerId[] = ["point-locations"];

const LAYER_ORDER: MapLayerId[] = [
  ...TOGGLEABLE_MAP_LAYERS,
  ...BOUNDARY_MAP_LAYERS,
];

export function isBoundaryMapLayer(
  layer: MapLayerId,
): layer is BoundaryMapLayerId {
  return BOUNDARY_MAP_LAYERS.includes(layer as BoundaryMapLayerId);
}

export function getBoundaryMapLayer(
  layers: readonly MapLayerId[],
): BoundaryMapLayerId | null {
  return layers.find(isBoundaryMapLayer) ?? null;
}

export function getToggleableMapLayers(
  layers: readonly MapLayerId[],
): ToggleableMapLayerId[] {
  return TOGGLEABLE_MAP_LAYERS.filter((layer) => layers.includes(layer));
}

export function parseMapLayersParam(value: unknown): MapLayerId[] {
  if (typeof value !== "string") return [...DEFAULT_MAP_LAYERS];
  if (value === "") return [];

  const requested = value.split(",").map((layer) => layer.trim());
  const boundaryCount = requested.filter((layer) =>
    BOUNDARY_MAP_LAYERS.includes(layer as BoundaryMapLayerId),
  ).length;
  if (
    requested.length === 0 ||
    new Set(requested).size !== requested.length ||
    requested.some((layer) => !LAYER_ORDER.includes(layer as MapLayerId)) ||
    boundaryCount > 1 ||
    (boundaryCount === 1 && requested.length > 1)
  ) {
    return [...DEFAULT_MAP_LAYERS];
  }

  return LAYER_ORDER.filter((layer) => requested.includes(layer));
}

export function formatMapLayersParam(layers: readonly MapLayerId[]): string {
  return LAYER_ORDER.filter((layer) => layers.includes(layer)).join(",");
}
