import { getPublicDownloadUrl } from "#shared/publicDownloads";

const unavailableManifest = { available: false } as const;

export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig(event);
  const manifestUrl = getPublicDownloadUrl(
    config.public.downloadsBaseUrl,
    config.public.apiBaseUrl,
    "manifest.json",
  );

  if (!manifestUrl) {
    console.warn(
      "Public download manifest URL is missing or did not pass the public URL guard.",
    );
    setResponseHeader(event, "Cache-Control", "no-store");
    return unavailableManifest;
  }

  try {
    const manifest = await $fetch<unknown>(manifestUrl, {
      headers: {
        Accept: "application/json",
        // Cloudflare Worker subrequests do not include a user agent by
        // default. The CloudFront distribution's managed WAF rules reject
        // such requests, so identify this server-side metadata fetch.
        "User-Agent": "Philadelphia-Gun-Violence-Dashboard/1.0",
      },
      responseType: "json",
      retry: 0,
      // A cold CloudFront edge can take longer than the ordinary warm-cache
      // response. Keep this comfortably below the page request's timeout so a
      // valid release manifest does not fall back to stale legacy file paths.
      timeout: 5_000,
    });
    setResponseHeader(
      event,
      "Cache-Control",
      "public, max-age=300, stale-while-revalidate=3600",
    );
    return manifest;
  } catch (error) {
    console.warn("Public download manifest request failed.", error);
    setResponseHeader(event, "Cache-Control", "no-store");
    return unavailableManifest;
  }
});
