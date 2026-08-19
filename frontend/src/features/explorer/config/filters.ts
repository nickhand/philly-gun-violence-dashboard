import type { FilterConfig } from "../types";
import { msToTimeString, timestampToTimeString } from "@/shared/utils/datetime";

/**
 * Get filter configurations for the shooting victims dashboard.
 *
 * Returns an array of filter definitions that control how data is filtered
 * and which UI controls are displayed in the sidebar.
 *
 * @param selectedYear - Currently selected year (affects date tooltip formatting)
 * @returns Array of filter configurations
 *
 * @example
 * ```typescript
 * const filterConfigs = getFilterConfigs(2024);
 * // Use in Arquero filtering or sidebar component
 * ```
 */
export function getFilterConfigs(selectedYear: number | null): FilterConfig[] {
  return [
    {
      name: "fatal",
      label: "Fatal shootings only",
      getFilter: (value: boolean) => (value ? true : null),
      kind: "switch",
      default: false,
    },
    {
      name: "has_court_case",
      label: "Court search returned a result",
      getFilter: (value: boolean) => (value ? true : null),
      kind: "switch",
      default: false,
    },
    {
      name: "sex",
      label: "Gender",
      getFilter: (value: string[]) => (d: string) => value.indexOf(d) !== -1,
      kind: "checkbox",
      categories: [
        { value: "M", text: "Male" },
        { value: "F", text: "Female" },
      ],
      default: ["M", "F"],
      ncol: 1,
    },
    {
      name: "race",
      label: "Race/Ethnicity",
      getFilter: (value: string[]) => (d: string) => value.indexOf(d) !== -1,
      kind: "checkbox",
      categories: [
        { value: "W", text: "White (Non-Hispanic)" },
        { value: "B", text: "Black (Non-Hispanic)" },
        { value: "H", text: "Hispanic (Black or White)" },
        { value: "A", text: "Asian" },
        { value: "Other/Unknown", text: "Other/Unknown" },
      ],
      default: ["W", "B", "H", "A", "Other/Unknown"],
      ncol: 1,
    },
    {
      name: "weekday",
      label: "Day of Week",
      getFilter: (value: number[]) => (d: number) => value.indexOf(d) !== -1,
      kind: "checkbox",
      categories: [
        { value: 0, text: "Sunday" },
        { value: 1, text: "Monday" },
        { value: 2, text: "Tuesday" },
        { value: 3, text: "Wednesday" },
        { value: 4, text: "Thursday" },
        { value: 5, text: "Friday" },
        { value: 6, text: "Saturday" },
      ],
      default: [0, 1, 2, 3, 4, 5, 6],
      ncol: 2,
    },
    {
      name: "timeInMs",
      label: "Time of Day",
      getFilter: (value) => [value[0], value[1] + 1],
      kind: "slider",
      default: [0, 86399999], // ms since midnight
      showHistogram: true,
      autoLimits: false,
      excludeMissing: false,
      tooltip: {
        formatter(msSinceMidnight) {
          return msToTimeString(msSinceMidnight);
        },
      },
    },
    {
      name: "dateInMs",
      label: "Date",
      getFilter: (value) => {
        const start = new Date(value[0]);
        start.setHours(0, 0, 0, 0);

        const end = new Date(value[1]);
        end.setHours(23, 59, 59, 999);
        return [start.getTime(), end.getTime()];
      },
      kind: "slider",
      showHistogram: true,
      autoLimits: true,
      excludeMissing: false,
      tooltip: {
        formatter: (ts) =>
          selectedYear === null
            ? timestampToTimeString(ts, "%-m/%-d/%y")
            : timestampToTimeString(ts, "%b %-d"),
      },
    },
    {
      name: "age",
      label: "Age",
      getFilter: (value, excludeMissing) => {
        return (d: number) => {
          const condition = d >= value[0] && d <= value[1];
          return excludeMissing
            ? d !== null && condition
            : d === null || condition;
        };
      },
      kind: "slider",
      default: [0, 100],
      showHistogram: true,
      autoLimits: false,
      excludeMissing: true,
      tooltip: {
        formatter: (value) => `${value}`,
      },
    },
  ];
}
