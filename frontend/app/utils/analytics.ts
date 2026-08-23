export type AnalyticsProperties = Record<string, unknown>;

interface AnalyticsClient {
  capture(event: string, properties?: AnalyticsProperties): unknown;
  init(
    key: string,
    options: {
      api_host: string;
      autocapture: boolean;
      capture_pageleave: boolean;
      capture_pageview: "history_change";
      disable_session_recording: boolean;
      persistence: "localStorage";
      person_profiles: "identified_only";
    },
  ): unknown;
}

type AnalyticsLoader = () => Promise<{ default: AnalyticsClient }>;

export interface AnalyticsOptions {
  apiHost?: string;
  enabled: boolean;
  key?: string;
}

const defaultLoader: AnalyticsLoader = async () => {
  const { default: posthog } = await import("posthog-js");
  return { default: posthog };
};

export function createAnalytics(loadClient: AnalyticsLoader = defaultLoader) {
  let client: AnalyticsClient | null = null;
  let initialization: Promise<void> | null = null;
  const pendingEvents: Array<{
    event: string;
    properties?: AnalyticsProperties;
  }> = [];

  function init({
    apiHost = "https://us.i.posthog.com",
    enabled,
    key,
  }: AnalyticsOptions): boolean {
    const projectKey = key?.trim();
    if (!enabled || !projectKey || initialization) return false;

    initialization = loadClient()
      .then(({ default: posthog }) => {
        posthog.init(projectKey, {
          api_host: apiHost,
          person_profiles: "identified_only",
          capture_pageview: "history_change",
          capture_pageleave: true,
          autocapture: false,
          persistence: "localStorage",
          disable_session_recording: true,
        });

        client = posthog;
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

    return true;
  }

  function track(event: string, properties?: AnalyticsProperties): void {
    if (client) {
      client.capture(event, properties);
    } else if (initialization) {
      pendingEvents.push({ event, properties });
    }
  }

  return { init, track };
}

const analytics = createAnalytics();

export const initAnalytics = analytics.init;
export const track = analytics.track;

export function getDownloadLinkProperties(
  target: EventTarget | null,
): AnalyticsProperties | null {
  if (!(target instanceof Element)) return null;

  const anchor = target.closest<HTMLAnchorElement>(
    "a[data-analytics-download][download]",
  );
  if (!anchor) return null;

  const dataSelection = anchor.dataset.analyticsDownload?.trim();
  const fileName = anchor.getAttribute("download")?.trim();
  const format = anchor.dataset.analyticsFormat?.trim().toLowerCase();
  const sourcePage = anchor.dataset.analyticsSource?.trim();
  if (!dataSelection || !fileName || !format || !sourcePage) return null;

  const dataset = anchor.dataset.analyticsDataset?.trim();
  const rawRecordCount = anchor.dataset.analyticsRecordCount?.trim();
  const recordCount = rawRecordCount ? Number(rawRecordCount) : null;
  const hasRecordCount =
    recordCount !== null && Number.isInteger(recordCount) && recordCount >= 0;

  return {
    data_selection: dataSelection,
    file_name: fileName,
    format,
    source_page: sourcePage,
    ...(dataset ? { dataset } : {}),
    ...(hasRecordCount ? { record_count: recordCount } : {}),
  };
}

export function getPrintProperties(
  target: EventTarget | null,
): AnalyticsProperties | null {
  if (!(target instanceof Element)) return null;

  const control = target.closest<HTMLElement>("[data-analytics-print]");
  const contentType = control?.dataset.analyticsPrint?.trim();
  const sourcePage = control?.dataset.analyticsSource?.trim();
  if (!contentType || !sourcePage) return null;

  return {
    content_type: contentType,
    source_page: sourcePage,
  };
}

export function getExternalLinkProperties(
  target: EventTarget | null,
  currentUrl: string,
): AnalyticsProperties | null {
  if (!(target instanceof Element)) return null;

  const anchor = target.closest<HTMLAnchorElement>("a[href]");
  if (!anchor || anchor.hasAttribute("download")) return null;

  let destination: URL;
  let current: URL;
  try {
    destination = new URL(anchor.href, currentUrl);
    current = new URL(currentUrl);
  } catch {
    return null;
  }

  if (!/^https?:$/.test(destination.protocol)) return null;
  if (
    destination.origin === current.origin &&
    !anchor.relList.contains("external")
  ) {
    return null;
  }

  const label = (anchor.getAttribute("aria-label") || anchor.textContent || "")
    .replace(/\s+/g, " ")
    .trim();
  return {
    label: label || destination.hostname,
    url: destination.href,
  };
}
