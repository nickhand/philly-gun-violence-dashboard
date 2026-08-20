import { describe, expect, it } from "vitest";

import {
  buildSitemapEntries,
  latestPublicationTimestamp,
  normalizePublicationTimestamp,
} from "../../../server/utils/sitemapFreshness";

const canonicalBaseUrl =
  "https://www.nickhand.dev/philly-gun-violence-map";

describe("sitemap publication freshness", () => {
  it("normalizes only complete publication timestamps", () => {
    expect(normalizePublicationTimestamp("2026-08-20T10:30:00-04:00")).toBe(
      "2026-08-20T14:30:00.000Z",
    );
    expect(normalizePublicationTimestamp("2026-08-20")).toBeNull();
    expect(normalizePublicationTimestamp("not-a-date")).toBeNull();
    expect(normalizePublicationTimestamp(null)).toBeNull();
  });

  it("finds the latest valid publication timestamp", () => {
    expect(
      latestPublicationTimestamp(
        "2026-08-20T13:00:00Z",
        "invalid",
        "2026-08-20T10:30:00-04:00",
      ),
    ).toBe("2026-08-20T14:30:00.000Z");
    expect(latestPublicationTimestamp(undefined, "2026-08-20")).toBeNull();
  });

  it("dates data-driven routes from the publications that change them", () => {
    const entries = buildSitemapEntries({
      canonicalBaseUrl: `${canonicalBaseUrl}/`,
      metadata: {
        shootings: { last_updated: "2026-08-20T10:00:00Z" },
        homicides: { last_updated: "2026-08-20T11:00:00Z" },
        courts: { last_updated: "2026-08-19T12:00:00Z" },
      },
      publicDownloadPublishedAt: "2026-08-20T12:00:00Z",
    });

    expect(entries).toEqual([
      { loc: canonicalBaseUrl, lastmod: "2026-08-20T11:00:00.000Z" },
      { loc: `${canonicalBaseUrl}/about` },
      {
        loc: `${canonicalBaseUrl}/data`,
        lastmod: "2026-08-20T12:00:00.000Z",
      },
      { loc: `${canonicalBaseUrl}/methodology` },
      {
        loc: `${canonicalBaseUrl}/stats`,
        lastmod: "2026-08-20T11:00:00.000Z",
      },
    ]);
  });

  it("keeps the complete sitemap undated when freshness is unavailable", () => {
    const entries = buildSitemapEntries({
      canonicalBaseUrl,
      metadata: {
        shootings: { last_updated: "2026-08-20" },
        homicides: null,
        courts: { last_updated: "unknown" },
      },
      publicDownloadPublishedAt: "",
    });

    expect(entries).toEqual([
      { loc: canonicalBaseUrl },
      { loc: `${canonicalBaseUrl}/about` },
      { loc: `${canonicalBaseUrl}/data` },
      { loc: `${canonicalBaseUrl}/methodology` },
      { loc: `${canonicalBaseUrl}/stats` },
    ]);
  });
});
