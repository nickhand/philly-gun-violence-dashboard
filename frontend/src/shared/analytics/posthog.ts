let initialized = false;
let posthogClient: typeof import("posthog-js").default | null = null;
let initialization: Promise<void> | null = null;
const pendingEvents: Array<{
  event: string;
  properties?: Record<string, unknown>;
}> = [];

/**
 * Initialize PostHog analytics.
 * Only runs in production with a valid API key.
 */
export function initAnalytics(): void {
  const key = import.meta.env.VITE_POSTHOG_KEY;

  if (!key || !import.meta.env.PROD || initialization) {
    return;
  }

  initialization = import("posthog-js")
    .then(({ default: posthog }) => {
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

      posthogClient = posthog;
      initialized = true;

      for (const { event, properties } of pendingEvents) {
        posthog.capture(event, properties);
      }
      pendingEvents.length = 0;
    })
    .catch(() => {
      // Analytics must never prevent the dashboard from loading.
      pendingEvents.length = 0;
      initialization = null;
    });
}

/**
 * Track a custom event with optional properties.
 * No-op if analytics is not initialized.
 */
export function track(
  event: string,
  properties?: Record<string, unknown>
): void {
  if (posthogClient) {
    posthogClient.capture(event, properties);
  } else if (initialization) {
    pendingEvents.push({ event, properties });
  }
}

/**
 * Composable for accessing PostHog instance.
 * Use this in components that need direct access to posthog.
 */
export function usePostHog() {
  return {
    get posthog() {
      return posthogClient;
    },
    get initialized() {
      return initialized;
    },
  };
}
