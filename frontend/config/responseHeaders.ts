export const STRICT_TRANSPORT_SECURITY = "max-age=31536000";

interface ResponseHeaderOptions {
  indexable: boolean;
  production: boolean;
}

export function createSharedResponseHeaders({
  indexable,
  production,
}: ResponseHeaderOptions): Record<string, string> {
  return {
    "Content-Security-Policy": "frame-ancestors 'none'",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    ...(production && indexable
      ? { "Strict-Transport-Security": STRICT_TRANSPORT_SECURITY }
      : {}),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    ...(indexable ? {} : { "X-Robots-Tag": "noindex, nofollow" }),
  };
}
