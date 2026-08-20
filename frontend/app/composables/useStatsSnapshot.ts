export interface YearStats {
  year: number;
  victims: number;
  homicides: number | null;
}

export interface CategorySummary {
  age: Record<string, number>;
  court: Record<string, number>;
  gender: Record<string, number>;
  outcome: Record<string, number>;
  race: Record<string, number>;
  total: number;
  year: number | null;
}

export interface StatsSnapshot {
  shootings_data_through: string;
  homicides_data_through: string;
  current_year: number;
  previous_year: number;
  minimum_year: number;
  total_victims_all_years: number;
  current_total: number;
  current_fatal: number;
  current_nonfatal: number;
  shootings_previous_ytd: number | null;
  shooting_percent_change: number | null;
  homicides_ytd: number | null;
  homicides_previous_ytd: number | null;
  homicide_percent_change: number | null;
  peak: YearStats;
  years: YearStats[];
  category_summaries: CategorySummary[];
}

export function useStatsSnapshot() {
  const config = useRuntimeConfig();
  const apiBaseUrl = String(config.public.apiBaseUrl).replace(/\/$/, "");

  return useAsyncData("stats-snapshot", () =>
    $fetch<StatsSnapshot>(`${apiBaseUrl}/stats.json`, { timeout: 5_000 }),
  );
}
