import {
  getPublicDownloadUrl,
  parsePublicDownloadManifest,
} from "#shared/publicDownloads";

import {
  buildSitemapEntries,
  latestPublicationTimestamp,
} from "../utils/sitemapFreshness";

const sourceRequestHeaders = {
  Accept: "application/json",
  "User-Agent": "Philadelphia-Gun-Violence-Dashboard/1.0",
};

async function optionalJson(url: string | null): Promise<unknown> {
  if (!url) return null;

  try {
    return await $fetch<unknown>(url, {
      headers: sourceRequestHeaders,
      responseType: "json",
      retry: 0,
      // The sitemap module's same-origin source request has its own 5-second
      // deadline. Finish first so this handler can always return the complete
      // undated fallback instead of letting the outer request abort.
      timeout: 3_000,
    });
  } catch (error) {
    console.warn(`Sitemap freshness source was unavailable: ${url}`, error);
    return null;
  }
}

export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig(event);
  const apiBaseUrl = String(config.public.apiBaseUrl).replace(/\/+$/, "");
  const manifestUrl = getPublicDownloadUrl(
    config.public.downloadsBaseUrl,
    config.public.apiBaseUrl,
    "manifest.json",
  );

  const [metadata, manifestValue] = await Promise.all([
    optionalJson(`${apiBaseUrl}/meta`),
    optionalJson(manifestUrl),
  ]);
  const manifest = parsePublicDownloadManifest(manifestValue);
  const urls = buildSitemapEntries({
    canonicalBaseUrl: String(config.public.canonicalBaseUrl),
    metadata,
    publicDownloadPublishedAt: manifest?.publishedAt,
  });
  const latest = latestPublicationTimestamp(
    ...urls.map((entry) => entry.lastmod),
  );

  if (latest) {
    setResponseHeader(
      event,
      "Cache-Control",
      "public, max-age=300, s-maxage=300, stale-while-revalidate=3600",
    );
  } else {
    // Do not cache an undated fallback. A later request should be able to pick
    // up source publication timestamps after a transient upstream failure.
    setResponseHeader(event, "Cache-Control", "no-store");
  }
  setResponseHeader(event, "X-Robots-Tag", "noindex, nofollow");

  return { urls };
});
