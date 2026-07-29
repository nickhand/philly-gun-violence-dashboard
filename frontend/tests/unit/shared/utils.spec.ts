import { describe, expect, it, vi } from "vitest";
import { msToTimeString, timestampToTimeString } from "@/shared/utils/datetime";
import { fetchAllPages } from "@/shared/utils/pagination";
import { rowsToGeoJSON } from "@/shared/utils/rowsToGeoJSON";
import { shootingRows } from "../../fixtures/shootings";

describe("datetime utilities", () => {
  it.each([
    [0, "12:00 AM"],
    [43_200_000, "12:00 PM"],
    [54_900_000, "3:15 PM"],
  ])("formats %i milliseconds as %s", (value, expected) => {
    expect(msToTimeString(value)).toBe(expected);
  });

  it("formats timestamps in UTC", () => {
    expect(timestampToTimeString(Date.UTC(2026, 0, 5))).toBe("January 05");
  });
});

describe("fetchAllPages", () => {
  it("follows next offsets and combines each page", async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce({
        type: "FeatureCollection",
        features: ["a", "b"],
        next_offset: 2,
        limit: 2,
        offset: 0,
        total: 3,
      })
      .mockResolvedValueOnce({
        type: "FeatureCollection",
        features: ["c"],
        next_offset: null,
        limit: 2,
        offset: 2,
        total: 3,
      });

    await expect(fetchAllPages(fetchPage, {}, 2)).resolves.toEqual({
      type: "FeatureCollection",
      features: ["a", "b", "c"],
    });
    expect(fetchPage).toHaveBeenNthCalledWith(1, { limit: 2, offset: 0 });
    expect(fetchPage).toHaveBeenNthCalledWith(2, { limit: 2, offset: 2 });
  });
});

describe("rowsToGeoJSON", () => {
  it("keeps valid map points and omits only rows without coordinates", () => {
    const collection = rowsToGeoJSON(shootingRows);

    expect(collection.features).toHaveLength(3);
    expect(collection.features.map((feature) => feature.properties.unique_id))
      .toEqual([1, 2, 4]);
  });
});
