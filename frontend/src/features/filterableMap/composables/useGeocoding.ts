import { ref } from "vue";

/**
 * Philadelphia bounding box for restricting geocoding results.
 * Format: [minLon, minLat, maxLon, maxLat]
 */
const PHILLY_BOUNDS = [-75.28, 39.87, -74.96, 40.14];

/**
 * Geocoding result from Nominatim API.
 */
export interface GeocodingResult {
  place_id: number;
  display_name: string;
  lat: string;
  lon: string;
  type: string;
  importance: number;
  address?: {
    house_number?: string;
    road?: string;
    neighbourhood?: string;
    suburb?: string;
    city?: string;
    state?: string;
    postcode?: string;
  };
}

/**
 * Simplified address result for display.
 */
export interface AddressResult {
  id: number;
  displayName: string;
  shortName: string;
  lat: number;
  lon: number;
}

/**
 * Composable for geocoding addresses using Nominatim (OpenStreetMap).
 * Free to use with rate limiting (1 request per second).
 */
export function useGeocoding() {
  const results = ref<AddressResult[]>([]);
  const isLoading = ref(false);
  const error = ref<string | null>(null);

  // Track last request time for rate limiting
  let lastRequestTime = 0;

  /**
   * Format a Nominatim result into a shorter display name.
   */
  function formatShortName(result: GeocodingResult): string {
    const addr = result.address;
    if (!addr) {
      // Fallback: take first two parts of display_name
      const parts = result.display_name.split(", ");
      return parts.slice(0, 2).join(", ");
    }

    const parts: string[] = [];

    // Street address
    if (addr.house_number && addr.road) {
      parts.push(`${addr.house_number} ${addr.road}`);
    } else if (addr.road) {
      parts.push(addr.road);
    }

    // Neighborhood or suburb
    if (addr.neighbourhood) {
      parts.push(addr.neighbourhood);
    } else if (addr.suburb) {
      parts.push(addr.suburb);
    }

    // ZIP code
    if (addr.postcode) {
      parts.push(addr.postcode);
    }

    return parts.length > 0
      ? parts.join(", ")
      : result.display_name.split(", ").slice(0, 2).join(", ");
  }

  /**
   * Search for addresses matching the query.
   * Results are restricted to Philadelphia area.
   */
  async function searchAddress(query: string): Promise<void> {
    // Clear previous results for empty query
    if (!query || query.trim().length < 3) {
      results.value = [];
      return;
    }

    // Rate limiting: ensure at least 1 second between requests
    const now = Date.now();
    const timeSinceLastRequest = now - lastRequestTime;
    if (timeSinceLastRequest < 1000) {
      await new Promise((resolve) =>
        setTimeout(resolve, 1000 - timeSinceLastRequest)
      );
    }

    isLoading.value = true;
    error.value = null;

    try {
      // Build Nominatim URL with Philadelphia bounds
      const params = new URLSearchParams({
        q: `${query}, Philadelphia, PA`,
        format: "json",
        addressdetails: "1",
        limit: "5",
        // Restrict to Philadelphia bounding box
        viewbox: PHILLY_BOUNDS.join(","),
        bounded: "1",
      });

      const response = await fetch(
        `https://nominatim.openstreetmap.org/search?${params}`,
        {
          headers: {
            // Required by Nominatim usage policy
            "User-Agent": "PhillyGunViolenceDashboard/1.0",
          },
        }
      );

      lastRequestTime = Date.now();

      if (!response.ok) {
        throw new Error(`Geocoding failed: ${response.status}`);
      }

      const data: GeocodingResult[] = await response.json();

      // Transform results
      results.value = data.map((result) => ({
        id: result.place_id,
        displayName: result.display_name,
        shortName: formatShortName(result),
        lat: parseFloat(result.lat),
        lon: parseFloat(result.lon),
      }));
    } catch (err) {
      error.value = err instanceof Error ? err.message : "Geocoding failed";
      results.value = [];
    } finally {
      isLoading.value = false;
    }
  }

  /**
   * Clear search results.
   */
  function clearResults(): void {
    results.value = [];
    error.value = null;
  }

  return {
    results,
    isLoading,
    error,
    searchAddress,
    clearResults,
  };
}
