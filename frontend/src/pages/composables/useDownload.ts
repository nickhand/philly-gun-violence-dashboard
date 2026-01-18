/**
 * useDownload Composable
 *
 * Handles data export functionality for the mapping dashboard.
 * Supports CSV and GeoJSON formats with optional boundary aggregation.
 *
 * @module useDownload
 */

import type { Ref, ComputedRef } from "vue";
import { useBoundariesStore } from "@/shared/stores/boundaries";
import { sourceIdToDataset } from "@/features/filterableMap/config/sources";
import type { LayerConfig } from "@/features/filterableMap/types";

// Types
interface Feature {
  type: "Feature";
  properties: Record<string, unknown> | null;
  geometry: GeoJSON.Geometry | null;
}

interface DownloadOptions {
  useFiltered: boolean;
  format: "csv" | "geojson";
  aggregateBy: string | null;
}

interface UseDownloadOptions {
  filteredFeatures: ComputedRef<Feature[]>;
  layers: Ref<LayerConfig[]>;
}

// Derived fields to exclude from data exports (internal use only)
const EXCLUDED_EXPORT_FIELDS = new Set([
  "dateInMs",
  "timeInMs",
  "weekday",
  "unique_id",
  "lon",
  "lat",
  "year",
]);

/**
 * Composable for handling data download/export functionality.
 *
 * @param options - Configuration options
 * @returns Download handler function
 */
export function useDownload({ filteredFeatures, layers }: UseDownloadOptions) {
  const boundariesStore = useBoundariesStore();

  /**
   * Clean features for export by removing internal/derived fields.
   * Creates a new array with cleaned properties (does not mutate original).
   */
  function cleanFeaturesForExport(features: Feature[]): Feature[] {
    return features.map((f) => {
      if (!f.properties) return f;

      const cleanedProperties: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(f.properties)) {
        if (!EXCLUDED_EXPORT_FIELDS.has(key)) {
          cleanedProperties[key] = value;
        }
      }

      return {
        ...f,
        properties: cleanedProperties,
      };
    });
  }

  /**
   * Convert features to CSV format.
   * Extracts properties from each feature and formats as CSV.
   */
  function convertToCSV(features: Feature[]): string {
    if (features.length === 0) return "";

    // Get all unique property keys from all features
    const allKeys = new Set<string>();
    features.forEach((f) => {
      if (f.properties) {
        Object.keys(f.properties).forEach((key) => allKeys.add(key));
      }
    });

    // Add lat/lng if geometry exists
    const hasGeometry = features.some((f) => f.geometry?.type === "Point");
    if (hasGeometry) {
      allKeys.add("latitude");
      allKeys.add("longitude");
    }

    const headers = Array.from(allKeys);

    // Build rows
    const rows = features.map((f) => {
      return headers.map((header) => {
        let value: unknown;

        if (header === "latitude" && f.geometry?.type === "Point") {
          value = (f.geometry as GeoJSON.Point).coordinates[1];
        } else if (header === "longitude" && f.geometry?.type === "Point") {
          value = (f.geometry as GeoJSON.Point).coordinates[0];
        } else {
          value = f.properties?.[header];
        }

        // Handle null/undefined
        if (value === null || value === undefined) return "";

        // Escape strings with commas or quotes
        const str = String(value);
        if (str.includes(",") || str.includes('"') || str.includes("\n")) {
          return `"${str.replace(/"/g, '""')}"`;
        }
        return str;
      });
    });

    // Combine headers and rows
    return [headers.join(","), ...rows.map((row) => row.join(","))].join("\n");
  }

  /**
   * Convert aggregated data to CSV format.
   */
  function convertAggregatedToCSV(
    data: Array<Record<string, unknown>>,
  ): string {
    if (data.length === 0) return "";

    const headers = Object.keys(data[0]);
    const rows = data.map((row) =>
      headers.map((h) => {
        const value = row[h];
        if (value === null || value === undefined) return "";
        const str = String(value);
        if (str.includes(",") || str.includes('"')) {
          return `"${str.replace(/"/g, '""')}"`;
        }
        return str;
      }),
    );

    return [headers.join(","), ...rows.map((row) => row.join(","))].join("\n");
  }

  /**
   * Aggregate features by a boundary layer.
   * Groups shooting features by the boundary column and computes summary statistics.
   */
  function aggregateByBoundary(
    features: Feature[],
    layerName: string,
  ): Array<Record<string, unknown>> {
    // Find the layer config to get the column name
    const layerConfig = layers.value.find((l) => l.name === layerName);
    if (!layerConfig || !layerConfig.column) {
      console.warn(`No column found for layer: ${layerName}`);
      return [];
    }

    const column = layerConfig.column;

    // Group by the boundary column
    const groups = new Map<
      string | number,
      { total: number; fatal: number; nonfatal: number }
    >();

    features.forEach((f) => {
      if (!f.properties) return;
      const key = f.properties[column];
      if (key === null || key === undefined) return;

      const keyStr = String(key);
      if (!groups.has(keyStr)) {
        groups.set(keyStr, { total: 0, fatal: 0, nonfatal: 0 });
      }

      const group = groups.get(keyStr)!;
      group.total += 1;
      if (f.properties.fatal === true) {
        group.fatal += 1;
      } else {
        group.nonfatal += 1;
      }
    });

    // Convert to array of records
    const results: Array<Record<string, unknown>> = [];
    groups.forEach((stats, key) => {
      results.push({
        [column]: key,
        total_shootings: stats.total,
        fatal: stats.fatal,
        nonfatal: stats.nonfatal,
      });
    });

    // Sort by total descending
    results.sort(
      (a, b) => (b.total_shootings as number) - (a.total_shootings as number),
    );

    return results;
  }

  /**
   * Join aggregated data with boundary GeoJSON features.
   * Fetches boundary data and merges shooting counts into feature properties.
   */
  async function joinAggregatedWithBoundaries(
    aggregated: Array<Record<string, unknown>>,
    layerName: string,
  ): Promise<GeoJSON.FeatureCollection> {
    // Find the layer config to get source and geoid column
    const layerConfig = layers.value.find((l) => l.name === layerName);
    if (!layerConfig || !layerConfig.source || !layerConfig.geoid) {
      console.warn(`No source/geoid found for layer: ${layerName}`);
      return { type: "FeatureCollection", features: [] };
    }

    // Get dataset name from source ID
    const dataset = sourceIdToDataset(layerConfig.source);
    if (!dataset) {
      console.warn(
        `Could not extract dataset from source: ${layerConfig.source}`,
      );
      return { type: "FeatureCollection", features: [] };
    }

    // Fetch boundary data
    const boundaryData = await boundariesStore.fetchBoundaryData(dataset);
    if (!boundaryData) {
      console.warn(`Failed to fetch boundary data for: ${dataset}`);
      return { type: "FeatureCollection", features: [] };
    }

    // Create lookup map from aggregated data
    const column = layerConfig.column || layerConfig.geoid;
    const statsMap = new Map<string, Record<string, unknown>>();
    aggregated.forEach((row) => {
      const key = String(row[column]);
      statsMap.set(key, row);
    });

    // Join with boundary features
    const joinedFeatures = boundaryData.features.map((boundaryFeature) => {
      const geoid = String(boundaryFeature.properties[layerConfig.geoid!]);
      const stats = statsMap.get(geoid) || {
        total_shootings: 0,
        fatal: 0,
        nonfatal: 0,
      };

      return {
        type: "Feature" as const,
        geometry: boundaryFeature.geometry,
        properties: {
          ...boundaryFeature.properties,
          total_shootings: stats.total_shootings ?? 0,
          fatal: stats.fatal ?? 0,
          nonfatal: stats.nonfatal ?? 0,
        },
      };
    });

    return {
      type: "FeatureCollection",
      features: joinedFeatures,
    };
  }

  /**
   * Download blob as file.
   * Creates temporary anchor element and triggers download.
   */
  function downloadBlob(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  /**
   * Handle data download request.
   * Exports features in requested format based on dialog options.
   */
  async function handleDownload(options: DownloadOptions): Promise<void> {
    const features = filteredFeatures.value;
    const timestamp = new Date().toISOString().split("T")[0];
    const suffix = options.useFiltered ? "filtered" : "all";

    // Handle aggregation if requested
    if (options.aggregateBy) {
      const aggregated = aggregateByBoundary(features, options.aggregateBy);
      const aggSlug = options.aggregateBy.toLowerCase().replace(/\s+/g, "-");

      if (options.format === "csv") {
        const csv = convertAggregatedToCSV(aggregated);
        const blob = new Blob([csv], { type: "text/csv" });
        downloadBlob(
          blob,
          `shootings-by-${aggSlug}-${suffix}-${timestamp}.csv`,
        );
      } else {
        // GeoJSON format - join with boundary geometries
        const geojson = await joinAggregatedWithBoundaries(
          aggregated,
          options.aggregateBy,
        );
        const blob = new Blob([JSON.stringify(geojson, null, 2)], {
          type: "application/json",
        });
        downloadBlob(
          blob,
          `shootings-by-${aggSlug}-${suffix}-${timestamp}.geojson`,
        );
      }
      return;
    }

    // No aggregation - export raw features (cleaned of internal fields)
    const cleanedFeatures = cleanFeaturesForExport(features);

    if (options.format === "geojson") {
      const geojson = {
        type: "FeatureCollection",
        features: cleanedFeatures,
      };
      const blob = new Blob([JSON.stringify(geojson, null, 2)], {
        type: "application/json",
      });
      downloadBlob(blob, `shootings-${suffix}-${timestamp}.geojson`);
    } else if (options.format === "csv") {
      const csv = convertToCSV(cleanedFeatures);
      const blob = new Blob([csv], { type: "text/csv" });
      downloadBlob(blob, `shootings-${suffix}-${timestamp}.csv`);
    }
  }

  return {
    handleDownload,
  };
}
