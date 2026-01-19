/**
 * Histograms Composable
 *
 * Manages histogram data for slider filters with showHistogram enabled.
 * Computes histograms from Arquero-filtered data, excluding each dimension's
 * own filter to show the full distribution.
 *
 * @module useHistograms
 */

import { ref, type Ref } from "vue";
import type { FilterConfig, HistogramBin } from "@/features/explorer/types";

/**
 * Return type for the useHistograms composable.
 */
interface UseHistogramsReturn {
  /** Map of filter name to histogram bin data */
  histograms: Ref<Map<string, HistogramBin[]>>;
  /** Initialize histograms for filters with showHistogram enabled */
  initializeHistograms: (
    filters: FilterConfig[],
    getHistogramData: (dimensionId: string, numBins?: number) => HistogramBin[],
  ) => void;
  /** Update all histograms (call when filters change) */
  updateHistograms: (
    getHistogramData: (dimensionId: string, numBins?: number) => HistogramBin[],
  ) => void;
}

/**
 * Creates histogram state management for slider filters.
 *
 * Usage:
 * ```ts
 * const { histograms, initializeHistograms, updateHistograms } = useHistograms();
 *
 * // After Arquero table is initialized
 * initializeHistograms(filterConfigs, getHistogramData);
 *
 * // When filters change
 * updateHistograms(getHistogramData);
 *
 * // Access histogram data
 * const ageHistogram = histograms.value.get('age');
 * ```
 *
 * @param numBins - Number of bins for histograms (default 30)
 * @returns Histogram state and operations
 */
export function useHistograms(numBins: number = 30): UseHistogramsReturn {
  const histograms = ref<Map<string, HistogramBin[]>>(new Map());

  // Store filter names that have histograms enabled
  const histogramFilterNames = ref<string[]>([]);

  /**
   * Initialize histograms for all slider filters with showHistogram enabled.
   *
   * @param filters - Filter configurations
   * @param getHistogramData - Function to get histogram data from Arquero table
   */
  function initializeHistograms(
    filters: FilterConfig[],
    getHistogramData: (dimensionId: string, numBins?: number) => HistogramBin[],
  ): void {
    histograms.value.clear();
    histogramFilterNames.value = [];

    // Find all slider filters with showHistogram enabled
    for (const filter of filters) {
      if (filter.kind === "slider" && filter.showHistogram) {
        histogramFilterNames.value.push(filter.name);

        // Compute initial histogram
        const bins = getHistogramData(filter.name, numBins);
        histograms.value.set(filter.name, bins);
      }
    }
  }

  /**
   * Update all histogram data (call when filters change).
   *
   * @param getHistogramData - Function to get histogram data from Arquero table
   */
  function updateHistograms(
    getHistogramData: (dimensionId: string, numBins?: number) => HistogramBin[],
  ): void {
    for (const filterName of histogramFilterNames.value) {
      const bins = getHistogramData(filterName, numBins);
      histograms.value.set(filterName, bins);
    }
  }

  return {
    histograms,
    initializeHistograms,
    updateHistograms,
  };
}
