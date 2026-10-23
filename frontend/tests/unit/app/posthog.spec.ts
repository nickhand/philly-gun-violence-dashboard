import { expect, it, vi } from "vitest";
import posthog from "posthog-js";

it("keeps explicit events, history pageviews and pageleave with the real SDK", async () => {
  vi.useFakeTimers();
  const events: Array<{ event: string; properties: Record<string, unknown> }> = [];
  const originalPushState = window.history.pushState;
  const originalReplaceState = window.history.replaceState;
  const originalUrl = window.location.href;

  try {
    posthog.init("phc_local_regression", {
      api_host: "https://analytics.example.test",
      autocapture: false,
      capture_pageleave: true,
      capture_pageview: "history_change",
      disable_session_recording: true,
      persistence: "localStorage",
      person_profiles: "identified_only",
      // Exercise SDK event creation without sending test data or loading code.
      advanced_disable_flags: true,
      disable_external_dependency_loading: true,
      opt_out_useragent_filter: true,
      before_send(event) {
        if (event) events.push({ event: event.event, properties: event.properties });
        return null;
      },
    });

    await vi.waitFor(() =>
      expect(events.filter(({ event }) => event === "$pageview")).toHaveLength(1),
    );
    posthog.capture("year_changed", { year: "2025" });
    expect(events).toContainEqual({
      event: "year_changed",
      properties: expect.objectContaining({ year: "2025" }),
    });

    window.history.pushState({}, "", "/analytics-regression");
    await Promise.resolve();
    expect(events.filter(({ event }) => event === "$pageview")).toHaveLength(2);
    expect(events.at(-1)?.properties.$current_url).toContain("/analytics-regression");

    window.dispatchEvent(new Event("pagehide"));
    expect(events.some(({ event }) => event === "$pageleave")).toBe(true);

    const button = document.createElement("button");
    document.body.appendChild(button);
    button.click();
    expect(events.some(({ event }) => event === "$autocapture")).toBe(false);
    expect(posthog.sessionRecordingStarted()).toBe(false);
    expect(posthog.config.persistence).toBe("localStorage");
    expect(posthog.config.person_profiles).toBe("identified_only");
  } finally {
    posthog.opt_out_capturing();
    window.history.pushState = originalPushState;
    window.history.replaceState = originalReplaceState;
    originalReplaceState.call(window.history, {}, "", originalUrl);
    localStorage.clear();
    vi.clearAllTimers();
  }
});
