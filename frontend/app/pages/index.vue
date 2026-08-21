<script setup lang="ts">
import { formatDataNumber } from "~/utils/formatData";
import {
  formatPercentChange,
  sumCompleteAnnualCounts,
} from "~/utils/formatStats";
import {
  DEFAULT_MAP_LAYERS,
  parseMapLayersParam,
  type MapLayerId,
} from "~/utils/mapLayers";
import {
  DEFAULT_MAP_VIEW,
  parseMapViewParam,
  type MapView,
} from "~/utils/mapView";
import {
  createDashboardPageProvenance,
  getDashboardEntityIds,
} from "~/utils/structuredData";

interface ShootingContext {
  fatal: number;
  nonfatal: number;
}

interface HomicideContext {
  comparison: string | null;
  count: number;
  mode: "all" | "current" | "past";
  year: number;
}

const route = useRoute();
const router = useRouter();
const { canonicalBaseUrl } = useRuntimeConfig().public;
const siteUrl = String(canonicalBaseUrl).replace(/\/$/, "");
const canonicalUrl = siteUrl;
const entityIds = getDashboardEntityIds(siteUrl);

const {
  data: stats,
  error: statsError,
  refresh,
  status,
} = await useStatsSnapshot();

const availableYears = computed(() =>
  [...(stats.value?.years ?? [])].sort((left, right) => right.year - left.year),
);

const selectedYear = computed<number | null | undefined>(() => {
  const snapshot = stats.value;
  if (!snapshot) return undefined;

  const queryValue = route.query.year;
  if (Array.isArray(queryValue)) return snapshot.current_year;
  if (queryValue === "All Years" || queryValue?.toLowerCase() === "all") {
    return null;
  }

  const parsed = typeof queryValue === "string" ? Number(queryValue) : NaN;
  return Number.isInteger(parsed) &&
    snapshot.years.some(({ year }) => year === parsed)
    ? parsed
    : snapshot.current_year;
});

const selectedYearValue = computed(() => {
  if (selectedYear.value === null) return "All Years";
  return selectedYear.value === undefined ? "" : String(selectedYear.value);
});

const selectedMapView = computed<MapView>(() => {
  const queryValue = route.query.map;
  if (Array.isArray(queryValue)) return DEFAULT_MAP_VIEW;
  return parseMapViewParam(queryValue) ?? DEFAULT_MAP_VIEW;
});

const selectedMapLayers = computed<MapLayerId[]>(() => {
  if (!stats.value) return [...DEFAULT_MAP_LAYERS];
  const queryValue = route.query.layers;
  if (Array.isArray(queryValue)) return [...DEFAULT_MAP_LAYERS];
  return parseMapLayersParam(queryValue);
});

const selectedCategorySummary = computed(() => {
  const snapshot = stats.value;
  const year = selectedYear.value;
  if (!snapshot || year === undefined) return undefined;
  return snapshot.category_summaries?.find((summary) => summary.year === year);
});

function comparisonText(current: number, previous: number | null): string | null {
  if (previous === null || previous === 0) return null;
  const change = Math.round(100 * (current / previous - 1));
  return formatPercentChange(change);
}

const allYearsHomicidesIncomplete = computed(() => {
  const snapshot = stats.value;
  return (
    selectedYear.value === null &&
    Boolean(snapshot?.years.some(({ homicides }) => homicides === null))
  );
});

const homicideContext = computed<HomicideContext | null>(() => {
  const snapshot = stats.value;
  const year = selectedYear.value;
  if (!snapshot || year === undefined) return null;

  if (year === null) {
    const count = sumCompleteAnnualCounts(
      snapshot.years.map((item) => item.homicides),
    );
    if (count === null) return null;
    return {
      comparison: null,
      count,
      mode: "all",
      year: snapshot.minimum_year,
    };
  }

  if (year === snapshot.current_year) {
    if (snapshot.homicides_ytd === null) return null;
    return {
      comparison:
        snapshot.homicide_percent_change === null
          ? comparisonText(
              snapshot.homicides_ytd,
              snapshot.homicides_previous_ytd,
            )
          : formatPercentChange(snapshot.homicide_percent_change),
      count: snapshot.homicides_ytd,
      mode: "current",
      year,
    };
  }

  const selected = snapshot.years.find((item) => item.year === year);
  if (selected?.homicides === null || selected?.homicides === undefined) {
    return null;
  }
  const previous = snapshot.years.find((item) => item.year === year - 1);
  return {
    comparison: comparisonText(selected.homicides, previous?.homicides ?? null),
    count: selected.homicides,
    mode: "past",
    year,
  };
});

const shootingContext = computed<ShootingContext | null>(() => {
  const summary = selectedCategorySummary.value;
  if (summary) {
    return {
      fatal: summary.outcome.true ?? 0,
      nonfatal: summary.outcome.false ?? 0,
    };
  }
  const snapshot = stats.value;
  if (!snapshot || selectedYear.value !== snapshot.current_year) return null;
  return {
    fatal: snapshot.current_fatal,
    nonfatal: snapshot.current_nonfatal,
  };
});

const preservedYearParams = computed(() =>
  Object.entries(route.query).flatMap(([name, value]) => {
    if (name === "year" || name === "layers" || typeof value !== "string") {
      return [];
    }
    return [{ name, value }];
  }),
);

function changeYear(event: Event): void {
  const value = (event.target as HTMLSelectElement).value;
  const currentYear = stats.value?.current_year;
  void router.replace({
    query: {
      ...route.query,
      layers: undefined,
      year: value === String(currentYear) ? undefined : value,
    },
  });
}

const description =
  "Explore an interactive map and current data on fatal and nonfatal shooting victims in Philadelphia.";

useSeoMeta({
  title: "Philadelphia Gun Violence Dashboard | Interactive Shootings Map & Data",
  description,
  ogType: "website",
  ogTitle: "Philadelphia Gun Violence Dashboard",
  ogDescription: description,
  ogUrl: canonicalUrl,
  ogImage: `${siteUrl}/og-image.png`,
  twitterCard: "summary_large_image",
  twitterTitle: "Philadelphia Gun Violence Dashboard",
  twitterDescription: description,
  twitterImage: `${siteUrl}/og-image.png`,
});

useHead(() => ({
  link: [{ rel: "canonical", href: canonicalUrl }],
  script: [
    {
      type: "application/ld+json",
      innerHTML: JSON.stringify({
        "@context": "https://schema.org",
        "@type": "WebPage",
        "@id": `${canonicalUrl}#webpage`,
        name: "Philadelphia Gun Violence Dashboard",
        url: canonicalUrl,
        description,
        ...createDashboardPageProvenance(entityIds),
        mainEntity: { "@id": entityIds.dashboardDataset },
        about: { "@id": entityIds.dashboardDataset },
      }).replace(/</g, "\\u003c"),
    },
  ],
}));
</script>

<template>
  <main id="main-content" class="civic-legacy-dashboard" tabindex="-1">
    <a class="usa-skipnav" href="#filters">Skip to filters</a>
    <a class="usa-skipnav" href="#charts">Skip to charts</a>

    <div class="civic-legacy-year-bar">
      <form method="get">
        <input
          v-for="parameter in preservedYearParams"
          :key="parameter.name"
          type="hidden"
          :name="parameter.name"
          :value="parameter.value"
        />
        <label for="dashboard-year">Viewing data for</label>
        <select
          id="dashboard-year"
          name="year"
          :class="{
            'civic-legacy-year-bar__select--all':
              selectedYearValue === 'All Years',
          }"
          :disabled="!stats"
          @change="changeYear"
        >
          <option v-if="!stats" value="">Years unavailable</option>
          <template v-else>
            <option
              value="All Years"
              :selected="selectedYearValue === 'All Years'"
            >
              All Years
            </option>
            <option
              v-for="item in availableYears"
              :key="item.year"
              :value="String(item.year)"
              :selected="selectedYearValue === String(item.year)"
            >
              {{ item.year }}
            </option>
          </template>
        </select>
        <button class="usa-sr-only" type="submit" :disabled="!stats">
          View year
        </button>
      </form>
    </div>

    <header class="civic-legacy-dashboard-header">
      <h1>Mapping Philadelphia's Gun Violence</h1>

      <p
        class="civic-legacy-dashboard-header__summary civic-legacy-dashboard-header__summary--homicide"
        :class="{ 'is-loading': !homicideContext }"
        aria-live="polite"
      >
        <span data-nosnippet>
          <template v-if="allYearsHomicidesIncomplete">
            An all-years homicide total is unavailable because one or more annual
            totals are missing.
          </template>
          <template v-else-if="homicideContext?.mode === 'all'">
            There {{ homicideContext.count === 1 ? "has" : "have" }} been
            <span class="fatal">
              {{ formatDataNumber(homicideContext.count) }}
              {{ homicideContext.count === 1 ? "homicide" : "homicides" }}
            </span>
            {{ " " }}<span class="date-color">since {{ homicideContext.year }}</span>.
          </template>
          <template v-else-if="homicideContext?.mode === 'past'">
            In total, there {{ homicideContext.count === 1 ? "was" : "were" }}
            <span class="fatal">
              {{ formatDataNumber(homicideContext.count) }}
              {{ homicideContext.count === 1 ? "homicide" : "homicides" }}
            </span>
            in
            <span class="date-color">
              {{ homicideContext.year }}{{ homicideContext.comparison ? "," : "" }}
            </span>
            <template v-if="homicideContext.comparison">
              {{ " " }}{{ homicideContext.comparison }} from
              {{ homicideContext.year - 1 }}
            </template>.
          </template>
          <template v-else-if="homicideContext">
            There {{ homicideContext.count === 1 ? "has" : "have" }} been
            <span class="fatal">
              {{ formatDataNumber(homicideContext.count) }}
              {{ homicideContext.count === 1 ? "homicide" : "homicides" }}
            </span>
            in
            <span class="date-color">
              {{ homicideContext.year }}{{ homicideContext.comparison ? "," : "" }}
            </span>
            <template v-if="homicideContext.comparison">
              {{ " " }}{{ homicideContext.comparison }} from
              {{ homicideContext.year - 1 }}
            </template>.
          </template>
          <template v-else>Homicide totals are temporarily unavailable.</template>
        </span>
      </p>

      <p
        class="civic-legacy-dashboard-header__summary civic-legacy-dashboard-header__summary--shooting"
        :class="{ 'is-loading': !shootingContext }"
        aria-live="polite"
      >
        <span data-nosnippet>
          <template v-if="shootingContext">
            This map shows the victims of gun violence:
            <span class="nonfatal">
              {{ formatDataNumber(shootingContext.nonfatal) }} nonfatal
            </span>
            and
            <span class="fatal">
              {{ formatDataNumber(shootingContext.fatal) }} fatal
            </span>
            shooting victims
            <template v-if="selectedYear === stats?.current_year">
              so far in <span class="date-color">{{ selectedYear }}.</span>
            </template>
            <template v-else-if="selectedYear === null">
              since <span class="date-color">{{ stats?.minimum_year }}.</span>
            </template>
            <template v-else>
              in <span class="date-color">{{ selectedYear }}.</span>
            </template>
          </template>
          <template v-else>&nbsp;</template>
        </span>
      </p>
    </header>

    <section
      id="explorer"
      class="civic-legacy-explorer-shell"
      aria-label="Explore the record"
      data-nosnippet
    >
      <ClientOnly v-if="stats && selectedYear !== undefined">
        <Suspense>
          <LazyDashboardExplorer
            :key="selectedYearValue"
            :year="selectedYear"
            :initial-category-summary="selectedCategorySummary"
            :initial-view="selectedMapView"
            :layers="selectedMapLayers"
          />
          <template #fallback>
            <DashboardExplorerFallback
              :summary="selectedCategorySummary"
              :year="selectedYear"
            />
          </template>
        </Suspense>
        <template #fallback>
          <DashboardExplorerFallback
            :summary="selectedCategorySummary"
            :year="selectedYear"
          />
        </template>
      </ClientOnly>

      <template v-else>
        <div
          class="civic-legacy-map-explorer civic-legacy-map-explorer--fallback"
        >
          <div class="civic-legacy-map-view">
            <div class="civic-legacy-explorer-state" role="status">
              <strong>Interactive records are temporarily unavailable.</strong>
              <button
                class="usa-button usa-button--outline"
                type="button"
                :disabled="status === 'pending'"
                @click="refresh"
              >
                {{ status === "pending" ? "Trying again…" : "Try again" }}
              </button>
            </div>
          </div>
          <aside
            id="filters"
            class="civic-legacy-sidebar"
            aria-label="Map filters"
          >
            <p class="civic-legacy-explorer-state">
              Filters are unavailable while detailed records cannot be loaded.
            </p>
          </aside>
        </div>
        <DashboardCategoryCharts :rows="[]" state="error" />
      </template>
    </section>

    <p v-if="statsError" class="usa-sr-only" role="status">
      Current totals could not be loaded.
    </p>
  </main>
</template>
