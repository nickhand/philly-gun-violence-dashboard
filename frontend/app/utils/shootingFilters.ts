import type { ShootingRow } from "./shootingRecords";

export type ShootingRangeDimension = "age" | "dateInMs" | "timeInMs";
export type ShootingCategoryDimension = "race" | "sex" | "weekday";
export type NumericRange = [number, number];

export interface ShootingFilterState {
  age: NumericRange;
  dateInMs: NumericRange;
  excludeUnknownAge: boolean;
  fatalOnly: boolean;
  hasCourtCase: boolean;
  race: string[];
  sex: string[];
  timeInMs: NumericRange;
  weekday: number[];
}

export interface ShootingHistogramBin {
  length: number;
  x0: number;
  x1: number;
}

export const AGE_RANGE: NumericRange = [0, 100];
export const TIME_RANGE: NumericRange = [0, 86_399_999];
export const SEX_VALUES = ["M", "F"] as const;
export const RACE_VALUES = ["W", "B", "H", "A", "Other/Unknown"] as const;
export const WEEKDAY_VALUES = [0, 1, 2, 3, 4, 5, 6] as const;

function finiteValues(
  rows: ShootingRow[],
  dimension: ShootingRangeDimension,
): number[] {
  return rows.flatMap((row) => {
    const value = row[dimension];
    return typeof value === "number" && Number.isFinite(value) ? [value] : [];
  });
}

export function createShootingFilterState(
  rows: ShootingRow[],
): ShootingFilterState {
  const dates = finiteValues(rows, "dateInMs");
  const firstDate = dates.length > 0 ? Math.min(...dates) : 0;
  const lastDate = dates.length > 0 ? Math.max(...dates) : firstDate;

  return {
    age: [...AGE_RANGE],
    dateInMs: [firstDate, lastDate],
    excludeUnknownAge: false,
    fatalOnly: false,
    hasCourtCase: false,
    race: [...RACE_VALUES],
    sex: [...SEX_VALUES],
    timeInMs: [...TIME_RANGE],
    weekday: [...WEEKDAY_VALUES],
  };
}

function isWithinRange(
  row: ShootingRow,
  dimension: ShootingRangeDimension,
  range: NumericRange,
  includeMissing: boolean,
): boolean {
  const value = row[dimension];
  if (value === null) {
    if (includeMissing) return true;
    // This mirrors the legacy escaped range predicate: null time values
    // coerce to midnight, while null date values fall below a real date range.
    return dimension === "timeInMs" && 0 >= range[0] && 0 <= range[1];
  }
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= range[0] &&
    value <= range[1]
  );
}

export function filterShootingRows(
  rows: ShootingRow[],
  filters: ShootingFilterState,
  excludeDimension?: ShootingRangeDimension,
): ShootingRow[] {
  return rows.filter((row) => {
    if (filters.fatalOnly && row.fatal !== true) return false;
    if (filters.hasCourtCase && row.has_court_case !== true) return false;
    if (!filters.sex.includes(String(row.sex))) return false;
    if (!filters.race.includes(String(row.race))) return false;
    if (
      typeof row.weekday !== "number" ||
      !filters.weekday.includes(row.weekday)
    ) {
      return false;
    }

    if (
      excludeDimension !== "timeInMs" &&
      !isWithinRange(row, "timeInMs", filters.timeInMs, false)
    ) {
      return false;
    }
    if (
      excludeDimension !== "dateInMs" &&
      !isWithinRange(row, "dateInMs", filters.dateInMs, false)
    ) {
      return false;
    }
    if (
      excludeDimension !== "age" &&
      !isWithinRange(row, "age", filters.age, !filters.excludeUnknownAge)
    ) {
      return false;
    }
    return true;
  });
}

export function shootingHistogram(
  rows: ShootingRow[],
  filters: ShootingFilterState,
  dimension: ShootingRangeDimension,
  thresholds = 30,
): ShootingHistogramBin[] {
  const domainValues = finiteValues(rows, dimension);
  if (domainValues.length === 0 || thresholds < 1) return [];
  const values = finiteValues(
    filterShootingRows(rows, filters, dimension),
    dimension,
  );
  const [minimum, maximum] =
    dimension === "age"
      ? AGE_RANGE
      : dimension === "timeInMs"
        ? TIME_RANGE
        : [Math.min(...domainValues), Math.max(...domainValues)];
  const span = Math.max(maximum - minimum, 1);
  const width = span / thresholds;
  const bins = Array.from({ length: thresholds }, (_, index) => ({
    length: 0,
    x0: minimum + width * index,
    x1: index === thresholds - 1 ? maximum : minimum + width * (index + 1),
  }));

  for (const value of values) {
    if (value < minimum || value > maximum) continue;
    const index = Math.min(
      thresholds - 1,
      Math.floor(((value - minimum) / span) * thresholds),
    );
    const target = bins[index];
    if (target) target.length += 1;
  }
  return bins;
}

function sameValues<T>(left: T[], right: T[]): boolean {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  );
}

export function hasActiveShootingFilters(
  filters: ShootingFilterState,
  defaults: ShootingFilterState,
): boolean {
  return (
    filters.age[0] !== defaults.age[0] ||
    filters.age[1] !== defaults.age[1] ||
    filters.dateInMs[0] !== defaults.dateInMs[0] ||
    filters.dateInMs[1] !== defaults.dateInMs[1] ||
    filters.timeInMs[0] !== defaults.timeInMs[0] ||
    filters.timeInMs[1] !== defaults.timeInMs[1] ||
    filters.excludeUnknownAge !== defaults.excludeUnknownAge ||
    filters.fatalOnly !== defaults.fatalOnly ||
    filters.hasCourtCase !== defaults.hasCourtCase ||
    !sameValues(filters.sex, defaults.sex) ||
    !sameValues(filters.race, defaults.race) ||
    !sameValues(filters.weekday, defaults.weekday)
  );
}
