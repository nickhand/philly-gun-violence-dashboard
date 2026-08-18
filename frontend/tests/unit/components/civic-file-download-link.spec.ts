import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import CivicFileDownloadLink from "../../../layers/civic-ui/app/components/CivicFileDownloadLink.vue";
import CivicIcon from "../../../layers/civic-ui/app/components/CivicIcon.vue";

type DownloadLinkProps = Record<string, unknown> & {
  filename?: string;
  format: string;
  href: string;
  sizeBytes?: number | null;
  variant?: "button" | "link";
};

function mountDownloadLink(
  props: DownloadLinkProps,
  attrs: Record<string, string> = {},
) {
  return mount(CivicFileDownloadLink, {
    props,
    attrs,
    slots: { default: "Download all shooting-victim records" },
    global: { components: { CivicIcon } },
  });
}

describe("CivicFileDownloadLink", () => {
  it("renders a descriptive native download link with nonredundant metadata", () => {
    const wrapper = mountDownloadLink(
      {
        filename: "philadelphia-shooting-victims.csv",
        format: "CSV",
        href: "https://data.example.test/philadelphia-shooting-victims.csv",
        sizeBytes: 3_064_024,
        variant: "button",
      },
      { type: "text/csv" },
    );
    const link = wrapper.get("a");
    const icon = link.get("svg.civic-icon");

    expect(link.attributes("href")).toBe(
      "https://data.example.test/philadelphia-shooting-victims.csv",
    );
    expect(link.attributes("download")).toBe(
      "philadelphia-shooting-victims.csv",
    );
    expect(link.attributes("type")).toBe("text/csv");
    expect(link.classes()).toEqual(
      expect.arrayContaining([
        "civic-file-download-link",
        "civic-file-download-link--button",
        "usa-button",
      ]),
    );
    expect(link.get(".civic-file-download-link__label").text()).toBe(
      "Download all shooting-victim records",
    );
    expect(link.get(".civic-file-download-link__metadata").text()).toBe(
      "[CSV, 3.1 MB]",
    );
    expect(icon.attributes("aria-hidden")).toBe("true");
    expect(icon.attributes("focusable")).toBe("false");
  });

  it("falls back to format-only metadata when no valid byte size is available", async () => {
    const wrapper = mountDownloadLink({
      format: "GeoJSON",
      href: "https://data.example.test/geography/neighborhoods.geojson",
      sizeBytes: null,
    });
    const metadata = wrapper.get(".civic-file-download-link__metadata");

    expect(metadata.text()).toBe("[GEOJSON]");
    expect(metadata.text()).not.toMatch(/undefined|null|NaN|,\s*\]/i);
    expect(wrapper.get("a").classes()).not.toContain(
      "civic-file-download-link--button",
    );

    await wrapper.setProps({ sizeBytes: Number.NaN });
    expect(metadata.text()).toBe("[GEOJSON]");
  });
});
