export interface DatasetMeta {
  data_through: string;
  last_updated: string;
  row_count?: number;
}

export interface AllDatasetsMeta {
  shootings: DatasetMeta;
  homicides: DatasetMeta;
  courts: DatasetMeta;
}

export function useDatasetMeta() {
  const config = useRuntimeConfig();
  const apiBaseUrl = String(config.public.apiBaseUrl).replace(/\/$/, "");

  return useFetch<AllDatasetsMeta>(`${apiBaseUrl}/meta`, {
    key: "dataset-meta",
    server: true,
    timeout: 5_000,
  });
}
