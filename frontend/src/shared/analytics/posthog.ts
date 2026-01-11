import posthog from "posthog-js";

let initialized = false;

/**
 * Initialize PostHog analytics.
 * Only runs in production with a valid API key.
 */
export function initAnalytics(): void {
  const key = import.meta.env.VITE_POSTHOG_KEY;

  if (!key) {
    console.log(
      "[Analytics] No PostHog key configured, skipping initialization"
    );
    return;
  }

  if (!import.meta.env.PROD) {
    console.log("[Analytics] Skipping PostHog in development mode");
    return;
  }

  posthog.init(key, {
    api_host: "https://us.i.posthog.com",

    // Only create person profiles for identified users
    person_profiles: "identified_only",

    // Automatic tracking
    capture_pageview: true,
    capture_pageleave: true,

    // Disable autocapture - we'll track manually for cleaner data
    autocapture: false,

    // Privacy settings
    persistence: "localStorage",
    disable_session_recording: true,
  });

  initialized = true;
  console.log("[Analytics] PostHog initialized");
}

/**
 * Track a custom event with optional properties.
 * No-op if analytics is not initialized.
 */
export function track(
  event: string,
  properties?: Record<string, unknown>
): void {
  if (!initialized) return;
  posthog.capture(event, properties);
}

/**
 * Composable for accessing PostHog instance.
 * Use this in components that need direct access to posthog.
 */
export function usePostHog() {
  return { posthog, initialized };
}
