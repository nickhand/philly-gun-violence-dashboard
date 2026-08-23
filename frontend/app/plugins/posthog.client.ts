import {
  getDownloadLinkProperties,
  getExternalLinkProperties,
  getPrintProperties,
  initAnalytics,
  track,
} from "~/utils/analytics";

export default defineNuxtPlugin(() => {
  const { posthogHost, posthogKey } = useRuntimeConfig().public;
  const enabled = initAnalytics({
    apiHost: String(posthogHost),
    enabled: import.meta.env.PROD,
    key: String(posthogKey),
  });
  if (!enabled) return;

  document.addEventListener("click", (event) => {
    const downloadProperties = getDownloadLinkProperties(event.target);
    if (downloadProperties) {
      track("data_download_requested", downloadProperties);
      return;
    }

    const printProperties = getPrintProperties(event.target);
    if (printProperties) {
      track("print_requested", printProperties);
      return;
    }

    const properties = getExternalLinkProperties(event.target, location.href);
    if (properties) track("external_link_clicked", properties);
  });
});
