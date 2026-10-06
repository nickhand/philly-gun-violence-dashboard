export interface MapView {
  center: [number, number];
  zoom: number;
}

export const DEFAULT_MAP_VIEW: MapView = {
  center: [-75.1652, 39.9526],
  zoom: 11,
};

export const MAP_MIN_ZOOM = 9;
export const MAP_MAX_ZOOM = 18;

const DECIMAL_NUMBER = /^-?(?:\d+(?:\.\d+)?|\.\d+)$/;

export function parseMapViewParam(value: unknown): MapView | null {
  if (typeof value !== "string") return null;

  const parts = value.split("/");
  if (parts.length !== 3 || parts.some((part) => !DECIMAL_NUMBER.test(part))) {
    return null;
  }

  const [zoom, latitude, longitude] = parts.map(Number);
  if (
    !Number.isFinite(zoom) ||
    !Number.isFinite(latitude) ||
    !Number.isFinite(longitude) ||
    zoom < MAP_MIN_ZOOM ||
    zoom > MAP_MAX_ZOOM ||
    latitude < -90 ||
    latitude > 90 ||
    longitude < -180 ||
    longitude > 180
  ) {
    return null;
  }

  return {
    center: [longitude, latitude],
    zoom,
  };
}

export function formatMapViewParam(view: MapView): string {
  const [longitude, latitude] = view.center;
  return `${view.zoom.toFixed(2)}/${latitude.toFixed(5)}/${longitude.toFixed(5)}`;
}
