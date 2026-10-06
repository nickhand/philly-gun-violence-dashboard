/**
 * useLoadingState Composable
 *
 * Centralizes loading state logic for the dashboard.
 * Combines store loading states with optional component-level ready states.
 *
 * @module useLoadingState
 */

import { computed, type Ref } from "vue";
import { storeToRefs } from "pinia";
import { useShootingsStore } from "@/shared/stores/shootings";

/**
 * Options for customizing loading state behavior.
 */
interface UseLoadingStateOptions {
  /**
   * Optional ref indicating if a component (e.g., map) is ready.
   * When provided, loading indicator shows until this is true.
   */
  componentReady?: Ref<boolean>;
}

/**
 * Creates centralized loading state computeds.
 *
 * @param options - Optional configuration
 * @returns Loading state computeds
 *
 * @example
 * ```typescript
 * // Basic usage (no component ready check)
 * const { showLoading, isLoading, hasError } = useLoadingState();
 *
 * // With map ready check
 * const mapReady = ref(false);
 * const { showLoading } = useLoadingState({ componentReady: mapReady });
 * ```
 */
export function useLoadingState(options: UseLoadingStateOptions = {}) {
  const shootingsStore = useShootingsStore();
  const { isLoading, loadError, metaError, hasData } =
    storeToRefs(shootingsStore);

  /**
   * Whether there's any error state.
   */
  const hasError = computed(() => !!loadError.value || metaError.value);

  /**
   * Whether the loading indicator should be shown.
   *
   * Shows loading when:
   * - Data is being fetched (initial load or year change)
   * - There's an error
   * - Data is ready but component isn't ready yet (if componentReady provided)
   */
  const showLoading = computed(() => {
    // Always show if fetching or error
    if (isLoading.value || hasError.value) {
      return true;
    }

    // If componentReady is provided, wait for it
    if (options.componentReady && hasData.value) {
      return !options.componentReady.value;
    }

    return false;
  });

  /**
   * Human-readable loading state for debugging.
   */
  const debugState = computed(() => ({
    isLoading: isLoading.value,
    hasData: hasData.value,
    loadError: loadError.value,
    metaError: metaError.value,
    componentReady: options.componentReady?.value ?? "N/A",
    showLoading: showLoading.value,
  }));

  return {
    /** Whether to show the loading indicator */
    showLoading,
    /** Whether data is being fetched (alias for isLoading) */
    isLoading,
    /** Whether there's an error */
    hasError,
    /** Whether initial data has loaded */
    hasData,
    /** Debug state object (for console logging) */
    debugState,
  };
}
