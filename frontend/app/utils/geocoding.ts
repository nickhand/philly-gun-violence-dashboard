export interface AddressResult {
  displayName: string;
  id: number;
  lat: number;
  lon: number;
  shortName: string;
}

interface GeocodingResult {
  address?: {
    house_number?: string;
    neighbourhood?: string;
    postcode?: string;
    road?: string;
    suburb?: string;
  };
  display_name?: unknown;
  lat?: unknown;
  lon?: unknown;
  place_id?: unknown;
}

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

const PHILADELPHIA_BOUNDS = {
  maxLat: 40.14,
  maxLon: -74.96,
  minLat: 39.87,
  minLon: -75.28,
};

function shortName(result: GeocodingResult, displayName: string): string {
  const address = result.address;
  if (!address) return displayName.split(", ").slice(0, 2).join(", ");

  const parts: string[] = [];
  if (address.house_number && address.road) {
    parts.push(`${address.house_number} ${address.road}`);
  } else if (address.road) {
    parts.push(address.road);
  }
  if (address.neighbourhood) parts.push(address.neighbourhood);
  else if (address.suburb) parts.push(address.suburb);
  if (address.postcode) parts.push(address.postcode);
  return parts.length > 0
    ? parts.join(", ")
    : displayName.split(", ").slice(0, 2).join(", ");
}

export async function searchPhiladelphiaAddresses(
  query: string,
  options: { fetcher?: Fetcher; signal?: AbortSignal } = {},
): Promise<AddressResult[]> {
  const value = query.trim();
  if (value.length < 3) return [];

  const params = new URLSearchParams({
    addressdetails: "1",
    bounded: "1",
    format: "jsonv2",
    limit: "5",
    q: `${value}, Philadelphia, PA`,
    viewbox: [
      PHILADELPHIA_BOUNDS.minLon,
      PHILADELPHIA_BOUNDS.minLat,
      PHILADELPHIA_BOUNDS.maxLon,
      PHILADELPHIA_BOUNDS.maxLat,
    ].join(","),
  });
  const fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis);
  const response = await fetcher(
    `https://nominatim.openstreetmap.org/search?${params}`,
    {
      headers: { Accept: "application/json" },
      signal: options.signal,
    },
  );
  if (!response.ok) {
    throw new Error(`Address search failed with ${response.status}.`);
  }

  const data: unknown = await response.json();
  if (!Array.isArray(data)) throw new Error("Invalid address search response.");

  return data.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const result = item as GeocodingResult;
    const id = Number(result.place_id);
    const lat = Number(result.lat);
    const lon = Number(result.lon);
    const displayName =
      typeof result.display_name === "string" ? result.display_name : "";
    if (
      !Number.isInteger(id) ||
      !displayName ||
      !Number.isFinite(lat) ||
      !Number.isFinite(lon) ||
      lat < PHILADELPHIA_BOUNDS.minLat ||
      lat > PHILADELPHIA_BOUNDS.maxLat ||
      lon < PHILADELPHIA_BOUNDS.minLon ||
      lon > PHILADELPHIA_BOUNDS.maxLon
    ) {
      return [];
    }
    return [
      {
        displayName,
        id,
        lat,
        lon,
        shortName: shortName(result, displayName),
      },
    ];
  });
}
