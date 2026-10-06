import { mount, type VueWrapper } from "@vue/test-utils";
import { nextTick } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import CivicInfoTooltip from "../../../layers/civic-ui/app/components/CivicInfoTooltip.vue";

const mountedWrappers: VueWrapper[] = [];

function mountTooltip({ attachToDocument = false } = {}) {
  const wrapper = mount(CivicInfoTooltip, {
    props: {
      label: "About fatality status",
      tooltipId: "fatality-help",
    },
    slots: {
      default: "Fatality status comes from the public record.",
    },
    ...(attachToDocument ? { attachTo: document.body } : {}),
  });
  mountedWrappers.push(wrapper);
  return wrapper;
}

function expectPanelOpen(wrapper: ReturnType<typeof mountTooltip>, open: boolean) {
  const style = wrapper.get(".civic-info-tooltip__panel").attributes("style") ?? "";
  expect(style.includes("display: none")).toBe(!open);
}

afterEach(() => {
  for (const wrapper of mountedWrappers.splice(0)) wrapper.unmount();
});

describe("CivicInfoTooltip", () => {
  it("opens on hover and closes after the pointer leaves", async () => {
    const wrapper = mountTooltip();

    expect(wrapper.classes()).not.toContain("civic-info-tooltip--open");
    expectPanelOpen(wrapper, false);

    await wrapper.trigger("pointerenter");
    expect(wrapper.classes()).toContain("civic-info-tooltip--open");
    expectPanelOpen(wrapper, true);
    expect(
      wrapper.get(".civic-info-tooltip__panel").attributes("role"),
    ).toBe("tooltip");

    await wrapper.trigger("pointerleave");
    expect(wrapper.classes()).not.toContain("civic-info-tooltip--open");
    expectPanelOpen(wrapper, false);
  });

  it("opens on focus and lets Escape dismiss it without moving focus", async () => {
    const wrapper = mountTooltip();
    const trigger = wrapper.get("button");
    const panel = wrapper.get(".civic-info-tooltip__panel");

    expect(trigger.attributes("aria-controls")).toBe("fatality-help");
    expect(trigger.attributes("aria-expanded")).toBe("false");
    expect(trigger.attributes("aria-haspopup")).toBe("dialog");
    expect(trigger.attributes("aria-describedby")).toBe("fatality-help");
    expect(trigger.text()).toContain("About fatality status");
    expect(panel.attributes("id")).toBe("fatality-help");
    expect(panel.attributes("role")).toBe("tooltip");
    expect(panel.attributes("aria-label")).toBeUndefined();

    await trigger.trigger("focusin");
    expect(wrapper.classes()).toContain("civic-info-tooltip--open");
    expect(trigger.attributes("aria-expanded")).toBe("false");
    expectPanelOpen(wrapper, true);

    await trigger.trigger("keydown", { key: "Escape" });
    expect(wrapper.classes()).not.toContain("civic-info-tooltip--open");
    expectPanelOpen(wrapper, false);

    await trigger.trigger("focusout");
    await trigger.trigger("focusin");
    expect(wrapper.classes()).toContain("civic-info-tooltip--open");

    await trigger.trigger("focusout");
    expect(wrapper.classes()).not.toContain("civic-info-tooltip--open");
  });

  it("toggles on repeated trigger clicks", async () => {
    const wrapper = mountTooltip();
    const trigger = wrapper.get("button");

    await trigger.trigger("click");
    expect(wrapper.classes()).toContain("civic-info-tooltip--open");
    expect(trigger.attributes("aria-expanded")).toBe("true");
    expect(trigger.attributes("aria-describedby")).toBeUndefined();
    expect(
      wrapper.get(".civic-info-tooltip__panel").attributes("role"),
    ).toBe("dialog");
    expect(
      wrapper.get(".civic-info-tooltip__panel").attributes("aria-label"),
    ).toBe("fatality status information");

    await trigger.trigger("click");
    expect(wrapper.classes()).not.toContain("civic-info-tooltip--open");
    expect(trigger.attributes("aria-expanded")).toBe("false");
  });

  it("closes from its accessible 44-pixel control and restores trigger focus", async () => {
    const wrapper = mountTooltip({ attachToDocument: true });
    const trigger = wrapper.get<HTMLButtonElement>(
      ".civic-info-tooltip__trigger",
    );

    await trigger.trigger("click");
    const close = wrapper.get<HTMLButtonElement>(
      'button[aria-label="Close fatality status information"]',
    );
    expect(close.text()).toContain("×");

    await close.trigger("click");
    expectPanelOpen(wrapper, false);
    expect(document.activeElement).toBe(trigger.element);
  });

  it("closes on an outside pointerdown but not one inside the panel", async () => {
    const wrapper = mountTooltip({ attachToDocument: true });
    const trigger = wrapper.get(".civic-info-tooltip__trigger");
    const panel = wrapper.get(".civic-info-tooltip__panel");

    await trigger.trigger("click");
    panel.element.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    await nextTick();
    expectPanelOpen(wrapper, true);

    document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    await nextTick();
    expectPanelOpen(wrapper, false);
  });
});
