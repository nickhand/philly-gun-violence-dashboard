import { formatDataNumber } from "./formatData";

interface HomicideComparisonSnapshot {
  homicide_percent_change: number | null;
  homicides_previous_ytd: number | null;
  homicides_ytd: number | null;
  previous_year: number;
}

export function formatPercentChange(change: number): string {
  if (change > 0) return `an increase of ${change}%`;
  if (change < 0) return `a decrease of ${Math.abs(change)}%`;
  return "no change";
}

export function sumCompleteAnnualCounts(
  counts: Array<number | null>,
): number | null {
  if (counts.length === 0 || counts.some((count) => count === null)) {
    return null;
  }
  return (counts as number[]).reduce((total, count) => total + count, 0);
}

export function formatHomicideComparison(
  snapshot?: HomicideComparisonSnapshot | null,
): string {
  if (!snapshot || snapshot.homicides_ytd === null) {
    return "The current homicide total is temporarily unavailable.";
  }
  if (snapshot.homicides_previous_ytd === null) {
    return `A same-period ${snapshot.previous_year} comparison is not available.`;
  }

  const current = formatDataNumber(snapshot.homicides_ytd);
  const previous = formatDataNumber(snapshot.homicides_previous_ytd);
  const change = snapshot.homicide_percent_change;

  if (change === null) {
    return `${current} homicides, compared with ${previous} at the same point in ${snapshot.previous_year}.`;
  }
  if (change === 0) {
    return `${current} homicides, unchanged from ${previous} at the same point in ${snapshot.previous_year}.`;
  }

  const direction = change > 0 ? "up" : "down";
  return `${current} homicides, ${direction} ${Math.abs(change)}% from ${previous} at the same point in ${snapshot.previous_year}.`;
}
