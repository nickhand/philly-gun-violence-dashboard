import { describe, expect, it } from "vitest";

import {
  getPublicDownloadUrl,
  parsePublicDownloadManifest,
} from "../../../shared/publicDownloads";

describe("getPublicDownloadUrl", () => {
  it("builds a stable URL below the configured public download base", () => {
    expect(
      getPublicDownloadUrl(
        "https://data.example.test/releases/current/?token=ignored#fragment",
        "https://api.example.test",
        "geography/philadelphia-neighborhoods.geojson",
      ),
    ).toBe(
      "https://data.example.test/releases/current/geography/philadelphia-neighborhoods.geojson",
    );
  });

  it.each([
    ["missing", ""],
    ["malformed", "not a URL"],
    ["non-HTTP", "javascript:alert(1)"],
    ["credentials", "https://user:secret@data.example.test/files"],
    ["same API origin", "https://api.example.test/downloads"],
    ["known API host", "https://philly-gun-violence-dashboard-api.fly.dev/files"],
    ["shootings endpoint", "https://files.example.test/shootings"],
    ["metadata endpoint", "https://files.example.test/meta"],
    ["OpenAPI endpoint", "https://files.example.test/openapi.json"],
    ["documentation endpoint", "https://files.example.test/docs"],
    ["absolute artifact URL", "https://files.example.test/downloads"],
  ])("rejects the %s base", (_label, base) => {
    const filename =
      _label === "absolute artifact URL"
        ? "https://attacker.example/file.csv"
        : "philadelphia-shooting-victims.csv";
    expect(
      getPublicDownloadUrl(
        base,
        "https://api.example.test",
        filename,
      ),
    ).toBeNull();
  });

  it.each(["../private.csv", "/private.csv", "folder//file.csv", "folder\\file.csv"])(
    "rejects the unsafe artifact path %s",
    (path) => {
      expect(
        getPublicDownloadUrl(
          "https://data.example.test/downloads",
          "https://api.example.test",
          path,
        ),
      ).toBeNull();
    },
  );
});

describe("parsePublicDownloadManifest", () => {
  const releaseId = "a".repeat(64);
  const checksum = "b".repeat(64);

  it("accepts the immutable v2 records and geography contract", () => {
    expect(
      parsePublicDownloadManifest({
        schema_version: 2,
        version: `sha256:${releaseId}`,
        published_at: "2026-08-17T20:00:00Z",
        downloads: [
          {
            id: "shooting_victims",
            kind: "records",
            label: "Philadelphia shooting-victim records",
            filename: "philadelphia-shooting-victims.csv",
            path: `releases/${releaseId}/philadelphia-shooting-victims.csv`,
            media_type: "text/csv; charset=utf-8",
            byte_size: 123,
            sha256: checksum,
            row_count: 4,
          },
          {
            id: "zip_codes",
            kind: "geography",
            label: "ZIP code boundaries",
            filename: "philadelphia-zip-codes.geojson",
            path: `releases/${releaseId}/geography/philadelphia-zip-codes.geojson`,
            media_type: "application/geo+json",
            byte_size: 456,
            sha256: checksum,
            row_count: 48,
            dataset: "zip_codes",
            join_field: "zip_code",
          },
        ],
      }),
    ).toMatchObject({
      schemaVersion: 2,
      version: `sha256:${releaseId}`,
      downloads: [
        {
          id: "shooting_victims",
          kind: "records",
          rowCount: 4,
        },
        {
          id: "zip_codes",
          kind: "geography",
          dataset: "zip_codes",
          joinField: "zip_code",
        },
      ],
    });
  });

  it("keeps the legacy v1 size contract readable during migration", () => {
    expect(
      parsePublicDownloadManifest({
        schema_version: 1,
        version: "sha256:legacy",
        published_at: "2026-08-17T20:00:00Z",
        downloads: [
          {
            filename: "philadelphia-shooting-victims.csv",
            path: "philadelphia-shooting-victims.csv",
            media_type: "text/csv; charset=utf-8",
            byte_size: 123,
          },
        ],
      }),
    ).toMatchObject({
      schemaVersion: 1,
      downloads: [{ byteSize: 123 }],
    });
  });

  it.each([
    {
      label: "a path outside its release",
      change: { path: "philadelphia-shooting-victims.csv" },
    },
    {
      label: "a duplicate id",
      duplicate: true,
    },
    {
      label: "a missing geography join field",
      kind: "geography",
    },
  ])("rejects v2 with $label", ({ change, duplicate, kind }) => {
    const entry = {
      id: "shooting_victims",
      kind: kind ?? "records",
      label: "Philadelphia shooting-victim records",
      filename: "philadelphia-shooting-victims.csv",
      path: `releases/${releaseId}/philadelphia-shooting-victims.csv`,
      media_type: "text/csv; charset=utf-8",
      byte_size: 123,
      sha256: checksum,
      row_count: 4,
      ...change,
    };
    expect(
      parsePublicDownloadManifest({
        schema_version: 2,
        version: `sha256:${releaseId}`,
        published_at: "2026-08-17T20:00:00Z",
        downloads: duplicate ? [entry, { ...entry }] : [entry],
      }),
    ).toBeNull();
  });
});
