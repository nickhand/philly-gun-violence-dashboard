import { timeParse, utcFormat } from "d3-time-format";

const parseIsoLike = timeParse("%Y-%m-%d %H:%M:%S");
const parseLegacy = timeParse("%Y/%m/%d %H:%M:%S");

export function parseIncidentDate(dateString: string): Date | null {
  const dt = parseIsoLike(dateString) ?? parseLegacy(dateString);
  return dt ?? null;
}

export function getMsSinceMidnight(ms: number): number {
  const dt = new Date(ms);
  return ms - dt.setHours(0, 0, 0, 0);
}

/**
 * Convert milliseconds since midnight to a time string.
 *
 * @param ms - Milliseconds since midnight
 * @returns Time string in format "H:MM AM/PM" (e.g., "3:45 PM", "12:05 AM")
 *
 * @example
 * ```typescript
 * msToTimeString(0)          // "12:00 AM"
 * msToTimeString(43200000)   // "12:00 PM"
 * msToTimeString(54900000)   // "3:15 PM"
 * ```
 */
export function msToTimeString(ms: number): string {
  let x = ms / 1000;
  x /= 60;
  const minutes = Math.floor(x % 60);
  x /= 60;
  let hours = Math.floor(x % 24);
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12;
  hours = hours ? hours : 12; // the hour '0' should be '12'
  const minutesStr = minutes < 10 ? "0" + minutes : minutes;
  return hours + ":" + minutesStr + " " + ampm;
}

/**
 * Convert a timestamp to a formatted date/time string.
 *
 * Uses d3-time-format patterns for formatting.
 * Formats in UTC to avoid timezone offset issues (the timestamps represent
 * wall-clock times stored as UTC).
 *
 * @param ts - Unix timestamp in milliseconds
 * @param pattern - d3-time-format pattern (default: "%B %d" - e.g., "January 15")
 * @returns Formatted date/time string
 *
 * @example
 * ```typescript
 * timestampToTimeString(1609459200000)                // "January 1"
 * timestampToTimeString(1609459200000, "%-m/%-d/%y")  // "1/1/21"
 * timestampToTimeString(1609459200000, "%b %-d")      // "Jan 1"
 * ```
 */
export function timestampToTimeString(ts: number, pattern = "%B %d"): string {
  const dt = new Date(ts);
  const formatTime = utcFormat(pattern);
  return formatTime(dt);
}
