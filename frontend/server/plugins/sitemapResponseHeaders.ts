import {
  getRequestHeader,
  getRequestURL,
  setResponseHeader,
  setResponseStatus,
} from "h3";

async function sitemapEtag(body: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(body),
  );
  const hex = [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
  return `"${hex}"`;
}

function ifNoneMatchMatches(value: string | undefined, etag: string): boolean {
  if (!value) return false;
  const opaqueTag = etag.replace(/^W\//, "");
  return value.split(",").some((candidate) => {
    const normalized = candidate.trim();
    return normalized === "*" || normalized.replace(/^W\//, "") === opaqueTag;
  });
}

export default defineNitroPlugin((nitroApp) => {
  nitroApp.hooks.hook("beforeResponse", async (event, response) => {
    if (
      !getRequestURL(event).pathname.endsWith("/sitemap.xml") ||
      typeof response.body !== "string"
    ) {
      return;
    }

    const etag = await sitemapEtag(response.body);
    setResponseHeader(event, "ETag", etag);
    setResponseHeader(
      event,
      "Cache-Control",
      "public, max-age=300, s-maxage=300, stale-while-revalidate=3600",
    );
    if (ifNoneMatchMatches(getRequestHeader(event, "if-none-match"), etag)) {
      setResponseStatus(event, 304);
      response.body = null;
    }
  });
});
