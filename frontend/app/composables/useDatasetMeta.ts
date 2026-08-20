import type { AllDatasetsMeta } from "../types/datasetMeta";

export type {
  AllDatasetsMeta,
  CourtDatasetMeta,
  DatasetMeta,
} from "../types/datasetMeta";

export function useDatasetMeta() {
  const config = useRuntimeConfig();
  const apiBaseUrl = String(config.public.apiBaseUrl).replace(/\/$/, "");

  return useFetch<AllDatasetsMeta>(`${apiBaseUrl}/meta`, {
    key: "dataset-meta",
    server: true,
    timeout: 5_000,
  });
}
