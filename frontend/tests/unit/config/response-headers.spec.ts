import { describe, expect, it } from "vitest";

import {
  createSharedResponseHeaders,
  STRICT_TRANSPORT_SECURITY,
} from "../../../config/responseHeaders";

describe("shared Nuxt response headers", () => {
  it("sets HSTS for the indexable production deployment", () => {
    const headers = createSharedResponseHeaders({
      indexable: true,
      production: true,
    });

    expect(headers["Strict-Transport-Security"]).toBe(
      STRICT_TRANSPORT_SECURITY,
    );
    expect(headers["X-Robots-Tag"]).toBeUndefined();
  });

  it("does not set HSTS on the non-indexable workers.dev staging deployment", () => {
    const headers = createSharedResponseHeaders({
      indexable: false,
      production: true,
    });

    expect(headers["Strict-Transport-Security"]).toBeUndefined();
    expect(headers["X-Robots-Tag"]).toBe("noindex, nofollow");
  });

  it("does not teach browsers an HSTS policy during local development", () => {
    const headers = createSharedResponseHeaders({
      indexable: true,
      production: false,
    });

    expect(headers["Strict-Transport-Security"]).toBeUndefined();
  });
});
