export const STRICT_TRANSPORT_SECURITY = "max-age=31536000";
export const EMBED_ALLOWED_ORIGIN = "https://savephillylives.org";

interface ResponseHeaderOptions {
  indexable: boolean;
  production: boolean;
}

export function createSharedResponseHeaders({
  indexable,
  production,
}: ResponseHeaderOptions): Record<string, string> {
  const allowPartnerEmbedding = production && indexable;

  return {
    "Content-Security-Policy": allowPartnerEmbedding
      ? `frame-ancestors 'self' ${EMBED_ALLOWED_ORIGIN}`
      : "frame-ancestors 'none'",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    ...(production && indexable
      ? { "Strict-Transport-Security": STRICT_TRANSPORT_SECURITY }
      : {}),
    "X-Content-Type-Options": "nosniff",
    ...(allowPartnerEmbedding ? {} : { "X-Frame-Options": "DENY" }),
    ...(indexable ? {} : { "X-Robots-Tag": "noindex, nofollow" }),
  };
}
