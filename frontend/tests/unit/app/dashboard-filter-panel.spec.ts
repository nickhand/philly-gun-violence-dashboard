import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import DashboardFilterPanel from "../../../app/components/DashboardFilterPanel.vue";

describe("DashboardFilterPanel", () => {
  it("keeps reset available outside collapsed disclosure content", async () => {
    const wrapper = mount(DashboardFilterPanel, {
      props: { modified: true, title: "Gender" },
      slots: { default: "<p>Filter options</p>" },
    });

    const disclosure = wrapper.get("details");
    const reset = wrapper.get('button[aria-label="Reset Gender filter"]');
    expect((disclosure.element as HTMLDetailsElement).open).toBe(false);
    expect(reset.element.closest("details")).toBeNull();

    await reset.trigger("click");
    expect(wrapper.emitted("reset")).toEqual([[]]);
  });

  it("omits reset at the default state", () => {
    const wrapper = mount(DashboardFilterPanel, {
      props: { modified: false, title: "Age" },
    });

    expect(wrapper.find("button").exists()).toBe(false);
  });
});
