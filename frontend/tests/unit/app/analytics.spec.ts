import { describe, expect, it, vi } from "vitest";

import {
  createAnalytics,
  getDownloadLinkProperties,
  getExternalLinkProperties,
  getPrintProperties,
} from "../../../app/utils/analytics";

function createClient() {
  return {
    capture: vi.fn(),
    init: vi.fn(),
  };
}

describe("Nuxt analytics", () => {
  it("stays disabled without both production mode and a project token", () => {
    const load = vi.fn();
    const analytics = createAnalytics(load);

    expect(analytics.init({ enabled: false, key: "phc_test" })).toBe(false);
    expect(analytics.init({ enabled: true, key: "" })).toBe(false);
    analytics.track("year_changed", { year: "2026" });

    expect(load).not.toHaveBeenCalled();
  });

  it("initializes with the migrated privacy settings and flushes queued events", async () => {
    const client = createClient();
    let finishLoading!: (module: { default: typeof client }) => void;
    const load = vi.fn(
      () =>
        new Promise<{ default: typeof client }>((resolve) => {
          finishLoading = resolve;
        }),
    );
    const analytics = createAnalytics(load);

    expect(
      analytics.init({
        apiHost: "https://us.i.posthog.com",
        enabled: true,
        key: " phc_test ",
      }),
    ).toBe(true);
    analytics.track("year_changed", { year: "2025" });
    expect(client.capture).not.toHaveBeenCalled();

    finishLoading({ default: client });
    await vi.waitFor(() => expect(client.init).toHaveBeenCalledTimes(1));

    expect(client.init).toHaveBeenCalledWith("phc_test", {
      api_host: "https://us.i.posthog.com",
      autocapture: false,
      capture_pageleave: true,
      capture_pageview: "history_change",
      disable_session_recording: true,
      persistence: "localStorage",
      person_profiles: "identified_only",
    });
    expect(client.capture).toHaveBeenCalledWith("year_changed", {
      year: "2025",
    });

    analytics.track("filter_toggled", { filter: "fatal" });
    expect(client.capture).toHaveBeenLastCalledWith("filter_toggled", {
      filter: "fatal",
    });
  });

  it("drops queued events and allows a retry when the SDK cannot load", async () => {
    const client = createClient();
    const load = vi
      .fn()
      .mockRejectedValueOnce(new Error("blocked"))
      .mockResolvedValueOnce({ default: client });
    const analytics = createAnalytics(load);

    expect(analytics.init({ enabled: true, key: "phc_test" })).toBe(true);
    analytics.track("location_searched", { found: true });
    await vi.waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(analytics.init({ enabled: true, key: "phc_test" })).toBe(true);
    await vi.waitFor(() => expect(client.init).toHaveBeenCalledTimes(1));
    expect(client.capture).not.toHaveBeenCalled();
  });

  it("recognizes external links without treating downloads as link clicks", () => {
    const anchor = document.createElement("a");
    anchor.href = "https://github.com/nickhand/project";
    anchor.innerHTML = "<span>Source code</span>";
    document.body.appendChild(anchor);

    expect(
      getExternalLinkProperties(
        anchor.querySelector("span"),
        "https://www.nickhand.dev/philly-gun-violence-map/",
      ),
    ).toEqual({
      label: "Source code",
      url: "https://github.com/nickhand/project",
    });

    anchor.setAttribute("download", "records.csv");
    expect(
      getExternalLinkProperties(
        anchor,
        "https://www.nickhand.dev/philly-gun-violence-map/",
      ),
    ).toBeNull();
  });

  it("describes annotated static downloads without collecting their URLs", () => {
    const anchor = document.createElement("a");
    anchor.href = "https://downloads.example.test/records.csv?signature=secret";
    anchor.download = "shooting-records.csv";
    anchor.dataset.analyticsDataset = "shooting_records";
    anchor.dataset.analyticsDownload = "all";
    anchor.dataset.analyticsFormat = "CSV";
    anchor.dataset.analyticsRecordCount = "1234";
    anchor.dataset.analyticsSource = "data";
    anchor.innerHTML = "<span>Download records</span>";

    expect(
      getDownloadLinkProperties(anchor.querySelector("span")),
    ).toEqual({
      data_selection: "all",
      dataset: "shooting_records",
      file_name: "shooting-records.csv",
      format: "csv",
      record_count: 1234,
      source_page: "data",
    });
    expect(getDownloadLinkProperties(document.body)).toBeNull();
  });

  it("describes annotated print controls from nested click targets", () => {
    const button = document.createElement("button");
    button.dataset.analyticsPrint = "annual_counts";
    button.dataset.analyticsSource = "stats";
    button.innerHTML = "<span>Print counts by year</span>";

    expect(getPrintProperties(button.querySelector("span"))).toEqual({
      content_type: "annual_counts",
      source_page: "stats",
    });
    expect(getPrintProperties(document.body)).toBeNull();
  });
});
