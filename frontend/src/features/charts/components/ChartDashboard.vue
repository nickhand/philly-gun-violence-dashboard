<template>
  <section
    v-if="features.length > 0"
    class="chart-dashboard"
    role="region"
    aria-label="Shooting Statistics Charts"
    tabindex="-1"
  >
    <h2 class="sr-only">Shooting Victim Statistics by Category</h2>
    <!-- Top row: Outcome, Court Cases, Gender -->
    <div class="chart-row">
      <HistogramChart
        :features="features"
        title="Outcome"
        accessor="fatal"
        :color="colors.coral"
        :categories="[true, false]"
        :aliases="{ true: 'Fatal', false: 'Nonfatal' }"
        :label-width="120"
      />
      <HistogramChart
        :features="features"
        title="Public Court Record"
        accessor="has_court_case"
        :color="colors.slate"
        :categories="[true, false]"
        :aliases="{ true: 'Yes', false: 'No' }"
        :label-width="100"
      />
      <HistogramChart
        :features="features"
        title="Gender"
        accessor="sex"
        :color="colors.sage"
        :categories="['M', 'F']"
        :aliases="{ M: 'Male', F: 'Female' }"
        :label-width="100"
      />
    </div>

    <!-- Bottom row: Race/Ethnicity, Age -->
    <div class="chart-row chart-row--bottom">
      <HistogramChart
        :features="features"
        title="Race/Ethnicity"
        accessor="race"
        :color="colors.teal"
        :categories="['W', 'B', 'H', 'A', 'Other/Unknown']"
        :aliases="{
          W: 'White (Non-Hispanic)',
          B: 'Black (Non-Hispanic)',
          H: 'Hispanic',
          A: 'Asian',
          'Other/Unknown': 'Other/Unknown',
        }"
        :short-aliases="{
          W: 'White',
          B: 'Black',
          H: 'Hispanic',
          A: 'Asian',
          'Other/Unknown': 'Other',
        }"
        :label-width="200"
        :responsive-label-width="90"
      />
      <HistogramChart
        :features="features"
        title="Age Group"
        accessor="age_group"
        :color="colors.mauve"
        :categories="[
          'Younger than 18',
          '18 to 30',
          '31 to 45',
          'Older than 45',
          'Unknown',
        ]"
        :aliases="{
          'Younger than 18': 'Under 18',
          '18 to 30': '18 to 30',
          '31 to 45': '31 to 45',
          'Older than 45': 'Over 45',
          Unknown: 'Unknown',
        }"
        :short-aliases="{
          'Younger than 18': '<18',
          '18 to 30': '18–30',
          '31 to 45': '31–45',
          'Older than 45': '45+',
          Unknown: '?',
        }"
        :label-width="120"
        :responsive-label-width="80"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
/**
 * ChartDashboard Component
 *
 * Container for summary statistics charts showing shooting data breakdowns.
 * Displays horizontal bar charts for various demographic and incident categories.
 *
 * Charts auto-update when filtered features change.
 *
 * @component
 */

import HistogramChart from "./HistogramChart.vue";
import { CHART_COLORS } from "@/shared/constants";

// Types
interface Feature {
  properties: Record<string, unknown> | null;
}

interface Props {
  /** Filtered GeoJSON features to visualize */
  features: Feature[];
}

defineProps<Props>();

// Use shared colorblind-safe palette
const colors = CHART_COLORS;
</script>

<style scoped>
.chart-dashboard {
  background-color: rgb(var(--v-theme-background));
  padding: 32px 48px 48px;
}

.chart-row {
  display: flex;
  flex-wrap: wrap;
  gap: 32px;
  margin-bottom: 40px;
}

.chart-row--bottom {
  margin-bottom: 0;
}

/* Large screens: 3 charts in top row, 2 in bottom */
.chart-row > * {
  flex: 1 1 300px;
  min-width: 0;
}

/* Medium screens (768px - 1200px): 2 per row, third wraps */
@media (max-width: 1200px) {
  .chart-dashboard {
    padding: 28px 32px 40px;
  }

  .chart-row {
    gap: 24px;
  }

  .chart-row > * {
    flex: 1 1 calc(50% - 12px);
    min-width: 280px;
  }
}

/* Small screens: single column */
@media (max-width: 768px) {
  .chart-dashboard {
    padding: 20px 8px 24px;
  }

  .chart-row {
    flex-direction: column;
    gap: 20px;
    margin-bottom: 20px;
  }

  .chart-row > * {
    flex: 1 1 100%;
    min-width: 0;
  }
}
</style>
