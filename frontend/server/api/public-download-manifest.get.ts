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
    setResponseHeader(event, "Cache-Control", "no-store");
    return unavailableManifest;
  }

  try {
    const manifest = await $fetch<unknown>(manifestUrl, {
      responseType: "json",
      retry: 0,
      timeout: 1_500,
    });
    setResponseHeader(
      event,
      "Cache-Control",
      "public, max-age=300, stale-while-revalidate=3600",
    );
    return manifest;
  } catch {
    setResponseHeader(event, "Cache-Control", "no-store");
    return unavailableManifest;
  }
});
