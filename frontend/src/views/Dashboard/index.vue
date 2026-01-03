<template>
  <div class="dashboard-view">
    <!-- Top app navbar -->
    <navbar
      :data-years="dataYearsLocal"
      :selected-year="selectedYear"
      :show-overlay="showOverlay"
    />

    <!-- Header message -->
    <header-message
      ref="headerMessage"
      :fatal="fatalCount"
      :nonfatal="nonfatalCount"
      :current-year="currentYear"
      :min-year="minYear"
      :selected-year="selectedYear"
      :latest-data-date="latestDataDate"
      :show-overlay="showOverlay"
    />

    <!-- Display dashboard when data is loaded -->
    <div v-if="shootingsData !== null">
      <!-- Map -->
      <mapping-dashboard
        ref="MappingDashboard"
        :data="shootingsData"
        :filters="filters"
        :layers="layers"
        :sources="sources"
        :download-config="downloadConfig"
        title="# Shooting Victims"
        marker-title="shooting victim"
        marker-short-title="victim"
        @update:filtered-data="filteredFeatures = $event"
        @map:ready="mapReady = true"
      />

      <!-- Charts -->
      <chart-dashboard ref="ChartDashboard" :filtered-data="filteredFeatures" />
    </div>
    <v-overlay
      v-if="currentError"
      :value="true"
      opacity="0.6"
      color="#353d42"
      class="dashboard-error-overlay"
    >
      <v-card class="error-modal" elevation="8">
        <div class="error-title">An error occurred</div>
        <div class="error-body">
          {{ currentError || defaultLoadErrorMessage }}
        </div>
        <div class="error-actions">
          <v-btn text color="#7ab5e5" class="mr-2" @click="dismissError">
            Dismiss
          </v-btn>
          <v-btn color="#7ab5e5" dark @click="retryLoad">Retry</v-btn>
        </div>
      </v-card>
    </v-overlay>
  </div>
</template>

<script lang="ts">
import { defineComponent } from "vue";
import Vue from "vue";
import { Route, NavigationGuardNext } from "vue-router";

// Local
import MappingDashboard from "@/components/MappingDashboard/index.vue";
import FilterableMap from "@/components/MappingDashboard/FilterableMap.vue";
import ChartDashboard from "./ChartDashboard/index.vue";
import HeaderMessage from "./HeaderMessage.vue";
import Navbar from "@/components/Navbar.vue";
import {
  getMsSinceMidnight,
  msToTimeString,
  timestampToTimeString,
} from "@/utils/datetime";
// Types
import {
  ShootingVictimsGeoJson,
  ShootingVictimsProperties,
  ShootingVictimsFeatures,
  RaceValues,
  SexValues,
} from "@/types/ShootingsData";
import { LayerConfig, TitleFunction } from "@/types/Layers";
import { SourceConfig } from "@/types/Sources";
import { FilterConfig } from "@/types/Filters";
import { DownloadConfig } from "@/types/DownloadConfig";
import { mapGetters } from "vuex";

// External
import { max } from "d3-array";
import { format } from "d3-format";

/**
 * The main dashboard component.
 */
export default defineComponent({
  name: "DashboardView",
  props: {},
  components: {
    Navbar,
    MappingDashboard,
    HeaderMessage,
    ChartDashboard,
  },
  data() {
    const defaultLoadErrorMessage =
      "We couldn’t load the shootings data right now. Please retry or try again later.";
    const store = (this as any).$store;
    const storeDataYears = store?.getters?.dataYears || [];
    const storeDataYearsError = store?.getters?.dataYearsError || false;

    return {
      /**
       * Local copy of data years so we can update after retrying without reload
       */
      dataYearsLocal: [...storeDataYears],

      /**
       * Store the previous route
       */
      prevRoute: null as null | string,

      /**
       * The filtered geojson features array
       */
      filteredFeatures: null as ShootingVictimsFeatures | null,

      /**
       * Whether the map is initialized
       */
      mapReady: false,

      /**
       * The count of fatal shootings
       */
      fatalCount: 0,

      /**
       * The count of nonfatal shootings
       */
      nonfatalCount: 0,

      /**
       * The latest date in the current data
       */
      latestDataDate: null as null | Date,

      /**
       * Minimum data year
       */
      minYear: 2015,

      /**
       * The current year
       */
      currentYear: new Date().getFullYear(),

      /**
       * Whether we are handling the initial year selection to avoid double-loading
       */
      handlingInitialYear: false,

      /**
       * Default message for failed loads
       */
      defaultLoadErrorMessage,
    };
  },
  mounted() {
    // Fetch data years on mount if we don't have them yet
    if (!this.dataYears || this.dataYears.length === 0) {
      this.initializeDataYears();
    } else {
      this.dataYearsLocal = [...this.dataYears];
      const yr = this.getYearFromRoute();
      if (yr !== undefined) {
        this.$store.dispatch("setSelectedYear", yr);
      }
    }
  },
  computed: {
    ...mapGetters([
      "dataYears",
      "dataYearsError",
      "selectedYear",
      "isFetchingYears",
      "currentData",
      "isLoadingData",
      "dataLoadError",
      "overlayHold",
    ]),

    shootingsData(): ShootingVictimsGeoJson | null {
      return this.currentData as ShootingVictimsGeoJson | null;
    },

    /**
     * Configuration options for when data is downloaded
     */
    downloadConfig(): DownloadConfig {
      return {
        rename: { school_name: "school_catchment" },
        exclude: [
          "segment_id",
          "latino",
          "age_group",
          "dateInMs",
          "timeInMs",
          "unique_id",
        ],
        formatters: {
          race: (d: RaceValues) => {
            let aliases = {
              W: "White (Non-Hispanic)",
              B: "Black (Non-Hispanic)",
              H: "Hispanic (Black or White)",
              A: "Asian",
              "Other/Unknown": "Other/Unknown",
            };
            return aliases[d];
          },
          fatal: (d: true | false) => {
            return d ? "Fatal" : "Nonfatal";
          },
          sex: (d: SexValues) => {
            let aliases = {
              M: "Male",
              F: "Female",
            };
            return aliases[d];
          },
          has_court_case: (d: true | false) => {
            return d ? "Yes" : "No";
          },
        },
      };
    },

    /**
     * Array of configuration options for map layers
     */
    layers(): LayerConfig[] {
      return [
        {
          name: "Police District",
          source: "police-district-geo",
          type: "fill",
          aggregated: true,
          overlay: true,
          column: "police_district",
          geoid: "police_district",
          tooltip: {
            formatter: this.aggregatedLayerTooltip(
              (d: { police_district: string }) =>
                `Police District #${d.police_district}`
            ),
            on: "mousemove",
          },
        },
        {
          name: "Council District",
          source: "council-district-geo",
          type: "fill",
          aggregated: true,
          overlay: true,
          column: "council_district",
          geoid: "council_district",
          tooltip: {
            formatter: this.aggregatedLayerTooltip(
              (d: { council_district: number }) =>
                `Council District #${d.council_district}`
            ),
            on: "mousemove",
          },
        },
        {
          name: "ZIP Code",
          source: "zip-code-geo",
          type: "fill",
          aggregated: true,
          overlay: true,
          column: "zip_code",
          geoid: "zip_code",
          tooltip: {
            formatter: this.aggregatedLayerTooltip(
              (d: { zip_code: number }) => `${d.zip_code}`
            ),
            on: "mousemove",
          },
        },
        {
          name: "Neighborhood",
          source: "neighborhood-geo",
          type: "fill",
          aggregated: true,
          overlay: true,
          column: "neighborhood",
          geoid: "neighborhood",
          tooltip: {
            formatter: this.aggregatedLayerTooltip(
              (d: { neighborhood: string }) => d.neighborhood
            ),
            on: "mousemove",
          },
        },
        {
          name: "PA House District",
          source: "house-district-geo",
          type: "fill",
          aggregated: true,
          overlay: true,
          column: "house_district",
          geoid: "house_district",
          tooltip: {
            formatter: this.aggregatedLayerTooltip(
              (d: { house_district: number }) =>
                `House District #${d.house_district}`
            ),
            on: "mousemove",
          },
        },
        {
          name: "PA Senate District",
          source: "senate-district-geo",
          type: "fill",
          aggregated: true,
          overlay: true,
          column: "senate_district",
          geoid: "senate_district",
          tooltip: {
            formatter: this.aggregatedLayerTooltip(
              (d: { senate_district: number }) =>
                `Senate District #${d.senate_district}`
            ),
            on: "mousemove",
          },
        },
        {
          name: "Elementary School Catchment",
          source: "elementary-school-geo",
          type: "fill",
          aggregated: true,
          overlay: true,
          column: "school_name",
          geoid: "school_name",
          tooltip: {
            formatter: this.aggregatedLayerTooltip(
              (d: { school_name: string }) => `${d.school_name}`
            ),
            on: "mousemove",
          },
        },
        {
          name: "City Limits",
          source: "city-limits-geo",
          type: "line",
          aggregated: false,
          static: true,
          paint: { "line-width": 4, "line-color": "#fff" },
          showOnStart: true,
        },
        {
          name: "Point locations",
          source: "shootings",
          type: "circle",
          aggregated: false,
          showOnStart: true,
          paint: {
            "circle-radius": this.getCircleRadiusStyle(),
            "circle-color": [
              "case",
              ["boolean", ["get", "fatal"], false],
              "#d84545",
              "#e5dc8e",
            ],
            "circle-stroke-width": 1,
            "circle-opacity": 0.7,
            "circle-stroke-color": [
              "case",
              ["boolean", ["get", "fatal"], false],
              "#af2828",
              "#d3c913",
            ],
          },
          tooltip: {
            on: "mouseenter",
            formatter: this.pointsLayerTooltip,
          },
        },
        {
          name: "Heat map",
          source: "shootings",
          type: "heatmap",
          aggregated: false,
          beforeId: "Point locations",
          paint: {
            "heatmap-intensity": {
              stops: [
                [11, 1],
                [15, 5],
              ],
            },
            "heatmap-color": [
              "interpolate",
              ["linear"],
              ["heatmap-density"],
              0,
              "rgba(0, 0, 0, 0)",
              0.1,
              "#120d31",
              0.2,
              "#331067",
              0.3,
              "#59157e",
              0.4,
              "#7e2482",
              0.5,
              "#a3307e",
              0.6,
              "#c83e73",
              0.7,
              "#e95462",
              0.8,
              "#fa7d5e",
              0.9,
              "#fea973",
              1.0,
              "#fed395",
            ],
            "heatmap-radius": [
              "interpolate",
              ["exponential", 1.5],
              ["zoom"],
              10,
              15,
              15,
              50,
            ],
            "heatmap-opacity": {
              default: 0.9,
              stops: [
                [12, 0.9],
                [17, 0.5],
              ],
            },
          },
        },
        {
          name: "Hot spots by street block",
          source: "streets-geo",
          type: "line",
          aggregated: true,
          column: "segment_id",
          geoid: "segment_id",
          legend: {
            colorScheme: "Plasma",
            scaleName: "Log",
            colorRange: [0.5, 1],
          },
          beforeId: "Point locations",
          paint: {
            "line-width": [
              "interpolate",
              ["linear"],
              ["zoom"],
              10,
              2,
              12,
              3,
              13,
              5,
            ],
          },
          tooltip: {
            formatter: this.aggregatedLayerTooltip(
              (d: { block_number: number; street_name: string }) =>
                `${d.block_number} ${d.street_name}`
            ),
            on: "mousemove",
          },
        },
      ];
    },

    /**
     * Array of configuration options for loading source data for map
     */
    sources(): SourceConfig[] {
      return [
        {
          name: "shootings",
          data: this.shootingsData,
          // NOTE: THIS MUST BE UNIQUE
          filterColumn: "unique_id",
        },
        {
          name: "city-limits-geo",
          url: "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/City_Limits/FeatureServer/0",
        },
        {
          name: "police-district-geo",
          url: "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Gun_Violence_Dashboard_Police_Districts/FeatureServer/0",
          outFields: ["police_district"],
          formatter: { police_district: (d: number | string) => `${d}` },
        },
        {
          name: "council-district-geo",
          url: "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Gun_Violence_Dashboard_Council_Districts/FeatureServer/0",
          outFields: ["council_district"],
          formatter: { council_district: (d: number | string) => `${d}` },
        },
        {
          name: "zip-code-geo",
          url: "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Gun_Violence_Dashboard_ZIP_Codes/FeatureServer/0",
          outFields: ["zip_code"],
          formatter: { zip_code: (d: number | string) => `${d}` },
        },
        {
          name: "neighborhood-geo",
          url: "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Gun_Violence_Dashboard_Neighborhoods/FeatureServer/0",
          outFields: ["neighborhood"],
        },
        {
          name: "senate-district-geo",
          url: "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Gun_Violence_Dashboard_PA_Senate_Districts/FeatureServer/0",
          outFields: ["senate_district"],
          formatter: { senate_district: (d: number | string) => `${d}` },
        },
        {
          name: "house-district-geo",
          url: "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Gun_Violence_Dashboard_PA_House_Districts/FeatureServer/0",
          outFields: ["house_district"],
          formatter: { house_district: (d: number | string) => `${d}` },
        },
        {
          name: "elementary-school-geo",
          url: "https://services.arcgis.com/fLeGjb7u4uXqeF9q/ArcGIS/rest/services/Gun_Violence_Dashboard_School_Catchments/FeatureServer/0",
          outFields: ["school_name"],
        },
        {
          name: "streets-geo",
          url: "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Gun_Violence_Dashboard_Streets/FeatureServer/0",
          outFields: ["segment_id", "street_name", "block_number"],
          whereColumn: "segment_id",
          filterColumn: "segment_id",
          batchSize: 2000,
          formatter: {
            segment_id: (d: number | string) => `${d}`,
          },
        },
      ];
    },

    /**
     * Array of configuration options different map filters
     */
    filters(): FilterConfig[] {
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
          label: "Incidents with court cases",
          getFilter: (value: boolean) => (value ? true : null),
          kind: "switch",
          default: false,
        },
        {
          name: "sex",
          label: "Gender",
          getFilter: (value: string[]) => (d: string) =>
            value.indexOf(d) !== -1,
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
          getFilter: (value: string[]) => (d: string) =>
            value.indexOf(d) !== -1,
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
          getFilter: (value: number[]) => (d: number) =>
            value.indexOf(d) !== -1,
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
            let start = new Date(value[0]);
            start.setHours(0, 0, 0, 0);

            let end = new Date(value[1]);
            end.setHours(23, 59, 59, 999);
            return [start.getTime(), end.getTime()];
          },
          kind: "slider",
          showHistogram: true,
          autoLimits: true,
          excludeMissing: false,
          tooltip: {
            formatter: (ts) =>
              this.selectedYear === null
                ? timestampToTimeString(ts, "%-m/%-d/%y")
                : timestampToTimeString(ts, "%b %-d"),
          },
        },
        {
          name: "age",
          label: "Age",
          getFilter: (value, excludeMissing) => {
            return (d: number) => {
              let condition = d >= value[0] && d <= value[1];
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
    },

    /**
     * Whether to show the loading overlay
     */
    showOverlay(): boolean {
      // Show overlay if loading, if there's an error, or if the map is initializing
      return (
        this.isFetchingYears ||
        this.isLoadingData ||
        this.overlayHold ||
        !!this.currentError ||
        (this.shootingsData !== null && !this.mapReady)
      );
    },

    /**
     * Current error message to display (either data years or data load)
     */
    currentError(): string | null {
      return (
        (this.dataYearsError ? this.defaultLoadErrorMessage : null) ||
        (this.dataLoadError as string | null)
      );
    },
  },
  watch: {
    /**
     * Sync local years when store updates
     */
    dataYears(newVal) {
      this.dataYearsLocal = newVal ? [...newVal] : [];
    },

    /**
     * When selected year in store changes, update local selectedYear and handle change
     */
    selectedYear(newYear, oldYear) {
      if (newYear === oldYear) return;
      if (this.handlingInitialYear) return;
      if (this.$route.path !== "/about" && newYear !== undefined) {
        const query = Object.assign({}, this.$route.query);
        query.year = newYear === null ? "All Years" : newYear.toString();
        this.$router.replace({ query }).catch((error) => {
          if (error.name !== "NavigationDuplicated") {
            throw error;
          }
        });
        this.handleYearChange(newYear);
      }
    },

    /**
     * Track the previous route when it changes and save it
     */
    $route: {
      handler(to: Route, from: Route) {
        if (from) this.prevRoute = from.path;
        const yr = this.getYearFromRoute();
        if (yr !== undefined && yr !== this.selectedYear && !this.handlingInitialYear) {
          this.$store.dispatch("setSelectedYear", yr);
        }
      },
      immediate: true,
    },
  },
  methods: {
    /**
     * Initialize data years from the store or fetch them if missing
     */
    async initializeDataYears() {
      this.handlingInitialYear = true;
      if (this.dataYears && this.dataYears.length > 0) {
        this.dataYearsLocal = [...this.dataYears];
        const initialYear = this.getYearFromRoute() ?? this.dataYearsLocal[0];
        await this.$store.dispatch("setSelectedYear", initialYear);
        await this.handleYearChange(initialYear);
      } else {
        const years = await this.fetchDataYears();
        if (years && years.length > 0) {
          this.dataYearsLocal = [...years];
          const initialYear = this.getYearFromRoute() ?? this.dataYearsLocal[0];
          await this.$store.dispatch("setSelectedYear", initialYear);
          await this.handleYearChange(initialYear);
        }
      }
      this.handlingInitialYear = false;
    },

    /**
     * Get selected year from route or default list
     */
    getYearFromRoute(): number | null | undefined {
      if (this.$route.path == "/about") return;
      if (this.prevRoute === "/about") return;

      let routeYear = this.$route.query?.year;
      let yearToSet: number | null | undefined;

      if (typeof routeYear == "string") {
        if (routeYear == "All Years") yearToSet = null;
        else yearToSet = parseInt(routeYear);
      } else {
        yearToSet = this.dataYearsLocal[0];
      }

      return yearToSet;
    },

    /**
     * Retry loading data for the current (or default) year
     */
    async retryLoad() {
      // Try to re-fetch data years if we don't have them
      if (this.dataYearsError || this.dataYearsLocal.length === 0) {
        const refreshedYears = await this.fetchDataYears();
        if (!refreshedYears) {
          return;
        }
        // After refreshing years, also refresh homicide totals if they previously failed
        this.refreshHomicideTotals();
      }

      const targetYear =
        this.selectedYear === undefined
          ? this.dataYearsLocal[0]
          : this.selectedYear;
      await this.handleYearChange(targetYear);
    },

    /**
     * Dismiss the current error to continue
     */
    dismissError() {
      this.$store.commit("setDataLoadError", null);
      this.$store.commit("setDataYearsError", false);
      // Keep overlay visible after dismissing the modal
      this.$store.commit("setOverlayHold", true);
    },

    /**
     * Refresh homicide totals in the header if available
     */
    refreshHomicideTotals() {
      const header = this.$refs.headerMessage as InstanceType<
        typeof HeaderMessage
      >;
      if (header && header.reloadHomicideTotals) {
        header.reloadHomicideTotals();
      }
    },

    /**
     * Fetch the list of available data years from GitHub via store
     */
    async fetchDataYears(): Promise<number[] | null> {
      const years = await (this as any).$store.dispatch("fetchDataYears");
      if (years && years.length) {
        this.dataYearsLocal = [...years];
      }
      return years;
    },

    /**
     * Update the prevRoute attribute before going to the next route
     */
    beforeRouteEnter(to: Route, from: Route, next: NavigationGuardNext) {
      next((vm: Vue & { prevRoute?: string | null }) => {
        vm.prevRoute = from.path;
        // Ensure data years are initialized when entering
        if (!(vm as any).dataYearsLocal?.length) {
          (vm as any).initializeDataYears();
        }
      });
    },

    /**
     * Based on the selected year, get the circle radius style.
     *
     * This uses smaller circles if we are showing data for all years.
     */
    getCircleRadiusStyle() {
      if (this.selectedYear === null) {
        return ["interpolate", ["exponential", 1.25], ["zoom"], 10, 1, 16, 9];
      } else
        return [
          "interpolate",
          ["exponential", 1.25],
          ["zoom"],
          10,
          3.5,
          16,
          11,
        ];
    },

    /**
     * Return a function that generates the tooltip string for
     * an aggregated layer from the data.
     *
     * @param titleFunc A function that returns the tooltip title
     */
    aggregatedLayerTooltip(titleFunc: TitleFunction): (data: any) => string {
      return (data) => {
        // Get the total count
        let count = data["count"];

        // The title
        let title = titleFunc(data);

        let text = `<div class='map-tooltip'>
                    <div class="map-tooltip__title">${title}</div>
                      <table class="w-100">
                        <tbody>
                          <tr class="map-tooltip__line">
                            <td class="map-tooltip__line-header">Count</td>
                            <td>${format(",.0f")(count)}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>`;
        return text;
      };
    },

    /**
     * Return a function that generates the tooltip string for
     * the points layer from the data.
     *
     * @param titleFunc A function that returns the tooltip title
     */
    pointsLayerTooltip(data: ShootingVictimsProperties) {
      let aliases = {
        W: "White (Non-Hispanic)",
        B: "Black (Non-Hispanic)",
        H: "Hispanic (Black or White)",
        M: "Male",
        F: "Female",
        A: "Asian",
      };
      let fatal = data.fatal ? "Fatal" : "Nonfatal";
      let arrest = data.has_court_case ? "Yes" : "No";
      let text = `<div class='map-tooltip'>
              <div class="map-tooltip__title">${fatal} Shooting</div>
              <table class="w-100">
                <tbody>
                  <tr class="map-tooltip__line">
                      <td>${new Date(data.date).toDateString()}</td>
                    </tr>
                  <tr class="map-tooltip__line">
                    <td>${msToTimeString(data.timeInMs)}</td>
                  </tr>
                  <tr class="map-tooltip__line">
                    <td>${data.block_number} ${data.street_name}</td>
                  </tr>
                </tbody>
              </table>
              <div class="map-tooltip__title mt-2">Victim Info</div>
              <table class="w-100">
                <tbody>`;

      if (data.age)
        text += `<tr class="map-tooltip__line">
                    <td>${data.age} years old</td>
                  </tr>`;

      if (data.race !== "Other/Unknown")
        text += `<tr class="map-tooltip__line">
                    <td>${aliases[data.race]}</td>
                  </tr>`;

      text += `<tr class="map-tooltip__line">
                    <td>${aliases[data.sex]}</td>
                  </tr>
                </tbody>
              </table>
              <div class="map-tooltip__title mt-2">Incident Info</div>
              <table class="w-100">
                <tbody>
                  <tr class="map-tooltip__line">
                    <td>DC #: ${data.dc_key}</td>
                  </tr>
                  <tr class="map-tooltip__line">
                    <td>Court Case: ${arrest}</td>
                  </tr>
                </tbody>
              </table>
            </div>`;
      return text;
    },

    /**
     * The main function to update the dashboard when the year changes
     * @param newYear Display data for the specified value
     */
    async handleYearChange(newYear: number | null) {
      // If we do not have valid data years, surface the error and bail
      if (this.dataYearsLocal.length === 0) {
        return;
      }

      try {
        const data = await this.$store.dispatch("fetchShootingsData", newYear);
        if (!data) {
          throw new Error("No data available for the requested year");
        }

        // Save
        this.filteredFeatures = data.features;
        // Update header counts immediately with the freshly loaded data
        this.updateHeaderMessage(data.features as ShootingVictimsFeatures);
        // Refresh homicide totals in case they previously failed
        this.refreshHomicideTotals();
        // Clear overlay hold when load succeeds
        this.$store.commit("setOverlayHold", false);

        // Make sure everything else has updated
        this.$nextTick(() => {
          // The dashboard
          let dashboard = this.$refs.MappingDashboard as InstanceType<
            typeof MappingDashboard
          >;
          if (dashboard === undefined) throw Error("Dashboard not found");

          // Reset all the filters to default values
          dashboard.resetDashboard();

          // Wait for reset to propagate
          this.$nextTick(() => {
            // Set the filtered data
            this.filteredFeatures =
              dashboard.filteredData as ShootingVictimsFeatures;

            // Update the map
            let map = dashboard.$refs.FilterableMap as InstanceType<
              typeof FilterableMap
            >;
            if (dashboard.mapReady && map.getLayer("Point locations")) {
              map.setPaintProperty(
                "Point locations",
                "circle-radius",
                this.getCircleRadiusStyle()
              );
            }

            // Update sliders in the dashboard
            dashboard.setDefaultSliderRanges();

            // Update variables for the header message
            if (this.filteredFeatures !== null)
              this.updateHeaderMessage(this.filteredFeatures);

            // Done loading!
          });
        });
      } catch (error) {
        console.error("Failed to load shootings data", error);
        this.filteredFeatures = null;
        this.fatalCount = 0;
        this.nonfatalCount = 0;
        this.latestDataDate = null;
      }
    },

    /**
     * Set the variables for the header message
     */
    updateHeaderMessage(data: ShootingVictimsFeatures) {
      // Set the max date
      let maxDateInMs = max(data, (d) => d.properties.dateInMs);
      if (maxDateInMs !== undefined)
        this.latestDataDate = new Date(maxDateInMs);

      // Set the fatal/nonfatal counts
      this.fatalCount = data.filter(
        (el) => el.properties.fatal === true
      ).length;
      this.nonfatalCount = data.length - this.fatalCount;
    },
  },
});
</script>

<style scoped>
.dashboard-error-overlay {
  z-index: 2000;
}
.error-modal {
  max-width: 440px;
  padding: 24px;
  text-align: left;
}
.error-title {
  font-size: 1.25rem;
  font-weight: 600;
  margin-bottom: 8px;
}
.error-body {
  font-size: 1rem;
  margin-bottom: 16px;
}
.error-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
