<script setup lang="ts">
import { computed } from "vue";

import CivicInfoTooltip from "../../layers/civic-ui/app/components/CivicInfoTooltip.vue";
import type { ShootingRow } from "~/utils/shootingRecords";

interface CategoryDefinition {
  label: string;
  shortLabel?: string;
  value: boolean | null | string;
}

interface ChartDefinition {
  accessor: keyof ShootingRow;
  categories: CategoryDefinition[];
  className: string;
  description: string;
  labelWidth: number;
  responsiveLabelWidth: number;
  title: string;
}

const props = withDefaults(
  defineProps<{
    rows: ShootingRow[];
    state?: "error" | "loading" | "ready";
  }>(),
  { state: "ready" },
);

const definitions: ChartDefinition[] = [
  {
    title: "Outcome",
    accessor: "fatal",
    className: "outcome",
    description:
      "Fatal indicates whether the Philadelphia Police Department shooting-victim record is classified as fatal.",
    labelWidth: 120,
    responsiveLabelWidth: 100,
    categories: [
      { value: true, label: "Fatal" },
      { value: false, label: "Nonfatal" },
    ],
  },
  {
    title: "Court Search Result",
    accessor: "has_court_case",
    className: "court",
    description:
      "Yes means the automated Pennsylvania court-portal search returned a result for the PPD incident number. No means a completed search returned an explicit no-results response. Unknown means the incident has not yet been checked or the search was unavailable, incomplete, or inconclusive. New incidents remain Unknown until a later completed court search. This flag does not establish how a record relates to a victim or report a case outcome.",
    labelWidth: 100,
    responsiveLabelWidth: 100,
    categories: [
      { value: true, label: "Yes" },
      { value: false, label: "No" },
      { value: null, label: "Unknown" },
    ],
  },
  {
    title: "Gender",
    accessor: "sex",
    className: "gender",
    description:
      "Categories reproduce the reported sex field in the Philadelphia Police Department source data, which supplies Male and Female values.",
    labelWidth: 100,
    responsiveLabelWidth: 100,
    categories: [
      { value: "M", label: "Male" },
      { value: "F", label: "Female" },
    ],
  },
  {
    title: "Race/Ethnicity",
    accessor: "race",
    className: "race",
    description:
      "Categories use the reported race field together with the source's Latino indicator. Other/Unknown groups remaining or unavailable values.",
    labelWidth: 200,
    responsiveLabelWidth: 90,
    categories: [
      { value: "W", label: "White (Non-Hispanic)", shortLabel: "White" },
      { value: "B", label: "Black (Non-Hispanic)", shortLabel: "Black" },
      { value: "H", label: "Hispanic" },
      { value: "A", label: "Asian" },
      {
        value: "Other/Unknown",
        label: "Other/Unknown",
        shortLabel: "Other",
      },
    ],
  },
  {
    title: "Age Group",
    accessor: "age_group",
    className: "age",
    description:
      "Age group is derived from reported age: under 18, 18 to 30, 31 to 45, over 45, or Unknown when age is unavailable.",
    labelWidth: 120,
    responsiveLabelWidth: 80,
    categories: [
      { value: "Younger than 18", label: "Under 18", shortLabel: "<18" },
      { value: "18 to 30", label: "18 to 30", shortLabel: "18–30" },
      { value: "31 to 45", label: "31 to 45", shortLabel: "31–45" },
      { value: "Older than 45", label: "Over 45", shortLabel: "45+" },
      { value: "Unknown", label: "Unknown", shortLabel: "?" },
    ],
  },
];

function formatPercents(counts: number[], total: number): string[] {
  if (total <= 0) return counts.map(() => "0");

  const rawPercents = counts.map((count) => (count / total) * 100);
  const smallestPositive = Math.min(
    ...rawPercents.filter((percent) => percent > 0),
  );
  const precision =
    smallestPositive < 0.01 ? 3 : smallestPositive < 0.1 ? 2 : 1;
  const scale = 10 ** precision;
  const rawUnits = rawPercents.map((percent) => percent * scale);
  const units = rawUnits.map(Math.floor);
  const representedCount = counts.reduce((sum, count) => sum + count, 0);
  let remainder =
    Math.round((representedCount / total) * 100 * scale) -
    units.reduce((sum, value) => sum + value, 0);
  const allocationOrder = rawUnits
    .map((value, index) => ({ fraction: value - units[index]!, index }))
    .sort((left, right) => right.fraction - left.fraction);

  for (const { index } of allocationOrder) {
    if (remainder <= 0) break;
    units[index]! += 1;
    remainder -= 1;
  }

  return units.map((value) =>
    (value / scale).toFixed(precision).replace(/\.0+$/, ""),
  );
}

const charts = computed(() =>
  definitions.map((definition) => {
    const values = definition.categories.map((category) => {
      const count = props.rows.reduce(
        (total, row) =>
          row[definition.accessor] === category.value ? total + 1 : total,
        0,
      );
      return {
        ...category,
        count,
      };
    });
    const percents = formatPercents(
      values.map((value) => value.count),
      props.rows.length,
    );
    const max = Math.max(0, ...values.map((value) => value.count));
    return {
      ...definition,
      max,
      values: values.map((value, index) => ({
        ...value,
        percent: percents[index] ?? "0",
      })),
    };
  }),
);

const emptyMessage = computed(() => {
  if (props.state === "loading") {
    return "Charts will appear after the detailed records load.";
  }
  if (props.state === "error") {
    return "Charts are unavailable while detailed records cannot be loaded.";
  }
  return "No shooting-victim records match the current filters.";
});

function chartStyle(chart: ChartDefinition): Record<string, string> {
  return {
    "--chart-label-width": `${chart.labelWidth}px`,
    "--chart-responsive-label-width": `${chart.responsiveLabelWidth}px`,
  };
}
</script>

<template>
  <section
    id="charts"
    class="civic-dashboard-category-charts"
    aria-label="Shooting Statistics Charts"
    role="region"
    tabindex="-1"
  >
    <h2 class="usa-sr-only">Shooting Victim Statistics by Category</h2>
    <p
      v-if="rows.length === 0"
      class="civic-dashboard-category-charts__empty"
      role="status"
    >
      {{ emptyMessage }}
    </p>
    <template v-else>
      <div class="civic-dashboard-category-charts__grid">
        <figure
          v-for="chart in charts"
          :key="chart.title"
          class="civic-dashboard-category-chart"
          :class="`civic-dashboard-category-chart--${chart.className}`"
          :style="chartStyle(chart)"
        >
          <figcaption>
            <span class="civic-dashboard-category-chart__title">
              {{ chart.title }}
            </span>
            <CivicInfoTooltip
              class="civic-dashboard-category-chart__definition"
              data-chart-definition
              :data-chart-definition-id="chart.className"
              :label="`About ${chart.title}`"
              :tooltip-id="`chart-definition-${chart.className}`"
              tone="inverse"
            >
              {{ chart.description }}
            </CivicInfoTooltip>
          </figcaption>
          <ul aria-hidden="true">
            <li v-for="item in chart.values" :key="String(item.value)">
              <span class="civic-dashboard-category-chart__name">
                <span class="civic-dashboard-category-chart__label--full">
                  {{ item.label }}
                </span>
                <span class="civic-dashboard-category-chart__label--short">
                  {{ item.shortLabel ?? item.label }}
                </span>
              </span>
              <div class="civic-dashboard-category-chart__plot">
                <div
                  class="civic-dashboard-category-chart__track"
                  :style="{
                    '--chart-bar-width': `${
                      chart.max > 0 ? (item.count / chart.max) * 100 : 0
                    }%`,
                  }"
                >
                  <span class="civic-dashboard-category-chart__bar"></span>
                  <span class="civic-dashboard-category-chart__value">
                    {{ item.count.toLocaleString() }}
                    <span class="civic-dashboard-category-chart__percent">
                      ({{ item.percent }}%)
                    </span>
                  </span>
                </div>
              </div>
            </li>
          </ul>
          <table
            class="usa-sr-only"
            :aria-label="`${chart.title} distribution breakdown`"
          >
            <caption>{{ chart.title }} distribution breakdown</caption>
            <thead>
              <tr>
                <th scope="col">Category</th>
                <th scope="col">Count</th>
                <th scope="col">Percentage</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in chart.values"
                :key="`table-${String(item.value)}`"
              >
                <td>{{ item.label }}</td>
                <td>{{ item.count }}</td>
                <td>{{ item.percent }}%</td>
              </tr>
            </tbody>
          </table>
        </figure>
      </div>
    </template>
  </section>
</template>

<style scoped>
.civic-dashboard-category-chart:has(.civic-info-tooltip--open) {
  z-index: 2;
}
</style>
