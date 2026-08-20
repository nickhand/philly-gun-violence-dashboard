<script setup lang="ts">
import DashboardCategoryCharts from "./DashboardCategoryCharts.vue";
import DashboardExplorerLoading from "./DashboardExplorerLoading.vue";
import type { CategorySummary } from "~/composables/useStatsSnapshot";

defineProps<{
  summary?: CategorySummary;
  year: number | null;
}>();
</script>

<template>
  <div class="civic-legacy-client-fallback">
    <DashboardExplorerLoading :year="year" />
    <DashboardCategoryCharts
      :rows="[]"
      :summary="summary"
      state="loading"
    />
  </div>
</template>
