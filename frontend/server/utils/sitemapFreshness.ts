const PUBLICATION_TIMESTAMP =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

export interface SitemapEntry {
  loc: string;
  lastmod?: string;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function normalizePublicationTimestamp(value: unknown): string | null {
  if (typeof value !== "string" || !PUBLICATION_TIMESTAMP.test(value)) {
    return null;
  }

  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : null;
}

export function latestPublicationTimestamp(
  ...values: unknown[]
): string | null {
  const timestamps = values
    .map(normalizePublicationTimestamp)
    .filter((value): value is string => value !== null);

  return timestamps.length > 0 ? timestamps.sort().at(-1) ?? null : null;
}

function datasetPublicationTimestamp(
  metadata: unknown,
  dataset: "shootings" | "homicides" | "courts",
): string | null {
  const datasets = recordValue(metadata);
  const entry = recordValue(datasets?.[dataset]);
  return normalizePublicationTimestamp(entry?.last_updated);
}

function withLastModified(
  loc: string,
  lastmod: string | null,
): SitemapEntry {
  return lastmod ? { loc, lastmod } : { loc };
}

export function buildSitemapEntries({
  canonicalBaseUrl,
  metadata,
  publicDownloadPublishedAt,
}: {
  canonicalBaseUrl: string;
  metadata: unknown;
  publicDownloadPublishedAt?: unknown;
}): SitemapEntry[] {
  const baseUrl = canonicalBaseUrl.replace(/\/+$/, "");
  const shootingsPublishedAt = datasetPublicationTimestamp(
    metadata,
    "shootings",
  );
  const homicidesPublishedAt = datasetPublicationTimestamp(
    metadata,
    "homicides",
  );
  const courtsPublishedAt = datasetPublicationTimestamp(metadata, "courts");
  const recordsPublishedAt = normalizePublicationTimestamp(
    publicDownloadPublishedAt,
  );

  return [
    withLastModified(
      baseUrl,
      latestPublicationTimestamp(
        shootingsPublishedAt,
        homicidesPublishedAt,
        courtsPublishedAt,
      ),
    ),
    { loc: `${baseUrl}/about` },
    withLastModified(
      `${baseUrl}/data`,
      latestPublicationTimestamp(
        shootingsPublishedAt,
        homicidesPublishedAt,
        courtsPublishedAt,
        recordsPublishedAt,
      ),
    ),
    { loc: `${baseUrl}/methodology` },
    withLastModified(
      `${baseUrl}/stats`,
      latestPublicationTimestamp(shootingsPublishedAt, homicidesPublishedAt),
    ),
  ];
}
