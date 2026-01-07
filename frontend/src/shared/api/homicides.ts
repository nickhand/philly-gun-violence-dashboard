import { apiFetch } from "@/shared/api/client";

/**
 * Annual and year-to-date homicide totals for a given year.
 */
export interface HomicideTotals {
  /** Calendar year of the totals */
  year: number;
  /** Annual total homicide count for the year (null if year not complete) */
  annual: number | null;
  /** Year-to-date homicide count */
  ytd: number;
}

/**
 * Fetches homicide totals for a specific year.
 *
 * @param year - The calendar year to fetch totals for
 * @returns Promise resolving to annual and YTD homicide totals
 * @throws Error if the API request fails or year not found
 *
 * @example
 * ```ts
 * const totals2024 = await fetchHomicideTotals(2024);
 * console.log(`YTD: ${totals2024.ytd}, Annual: ${totals2024.annual}`);
 * ```
 */
export async function fetchHomicideTotals(
  year: number
): Promise<HomicideTotals> {
  return apiFetch<HomicideTotals>(`/homicides/${year}`);
}
