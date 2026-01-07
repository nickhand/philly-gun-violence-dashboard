import { apiFetch } from "@/shared/api/client";
import { DataFeatureCollection } from "@/shared/types/sources";

export async function fetchBoundaryDatasets(): Promise<string[]> {
  // Boundaries are served directly from the API.
  const response = await apiFetch<{ datasets: string[] }>("/boundaries");
  return response.datasets;
}

export async function fetchBoundaryDataset(
  dataset: string
): Promise<DataFeatureCollection> {
  return apiFetch<DataFeatureCollection>(`/boundaries/${dataset}`);
}
