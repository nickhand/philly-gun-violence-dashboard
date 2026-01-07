const DEFAULT_API_BASE_URL =
  "https://philly-gun-violence-dashboard-api.fly.dev";

/**
 * Returns the base URL for the API, allowing for local overrides via environment variables.
 *
 * @returns The API base URL from environment variable or production default
 */
export function getApiBaseUrl(): string {
  // Allow local overrides while keeping the production default.
  return import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL;
}

/**
 * Fetches data from the API with automatic JSON parsing and error handling.
 *
 * @template T - The expected response type
 * @param path - API endpoint path (e.g., "/shootings/years")
 * @param init - Optional fetch configuration (headers, method, etc.)
 * @returns Promise resolving to the typed response data
 * @throws Error if the API request fails (non-2xx status)
 *
 * @example
 * ```ts
 * const years = await apiFetch<number[]>("/shootings/years");
 * const data = await apiFetch<FeatureCollection>("/shootings?year=2024");
 * ```
 */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  // Build the path to the full URL
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}${path}`;

  // Perform the fetch
  const response = await fetch(url, init);

  // Handle errors
  if (!response.ok) {
    throw new Error(
      `API request failed: ${response.status} ${response.statusText}`
    );
  }

  // Parse and return the JSON response with the expected type
  return (await response.json()) as T;
}
