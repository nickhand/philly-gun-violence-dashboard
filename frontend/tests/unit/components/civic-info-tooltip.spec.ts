import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import CivicInfoTooltip from "../../../layers/civic-ui/app/components/CivicInfoTooltip.vue";

function mountTooltip() {
  return mount(CivicInfoTooltip, {
    props: {
      label: "About fatality status",
      tooltipId: "fatality-help",
    },
    slots: {
      default: "Fatality status comes from the public record.",
    },
  });
}

function expectPanelOpen(wrapper: ReturnType<typeof mountTooltip>, open: boolean) {
  const style = wrapper.get('[role="tooltip"]').attributes("style") ?? "";
  expect(style.includes("display: none")).toBe(!open);
}

describe("CivicInfoTooltip", () => {
  it("opens on hover and closes after the pointer leaves", async () => {
    const wrapper = mountTooltip();

    expect(wrapper.classes()).not.toContain("civic-info-tooltip--open");
    expectPanelOpen(wrapper, false);

    await wrapper.trigger("pointerenter");
    expect(wrapper.classes()).toContain("civic-info-tooltip--open");
    expectPanelOpen(wrapper, true);

    await wrapper.trigger("pointerleave");
    expect(wrapper.classes()).not.toContain("civic-info-tooltip--open");
    expectPanelOpen(wrapper, false);
  });

  it("opens on focus and lets Escape dismiss it without moving focus", async () => {
    const wrapper = mountTooltip();
    const trigger = wrapper.get("button");
    const panel = wrapper.get('[role="tooltip"]');

    expect(trigger.attributes("aria-describedby")).toBe("fatality-help");
    expect(trigger.text()).toContain("About fatality status");
    expect(panel.attributes("id")).toBe("fatality-help");

    await trigger.trigger("focus");
    expect(wrapper.classes()).toContain("civic-info-tooltip--open");
    expectPanelOpen(wrapper, true);

    await trigger.trigger("keydown", { key: "Escape" });
    expect(wrapper.classes()).not.toContain("civic-info-tooltip--open");
    expectPanelOpen(wrapper, false);

    await trigger.trigger("blur");
    await trigger.trigger("focus");
    expect(wrapper.classes()).toContain("civic-info-tooltip--open");

    await trigger.trigger("blur");
    expect(wrapper.classes()).not.toContain("civic-info-tooltip--open");
  });

  it("opens on click and closes when its inactive pointer region is left", async () => {
    const wrapper = mountTooltip();
    const trigger = wrapper.get("button");

    await trigger.trigger("click");
    expect(wrapper.classes()).toContain("civic-info-tooltip--open");

    await wrapper.trigger("pointerleave");
    expect(wrapper.classes()).not.toContain("civic-info-tooltip--open");
  });
});
