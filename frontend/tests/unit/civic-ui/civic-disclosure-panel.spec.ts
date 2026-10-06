import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import CivicDisclosurePanel from "../../../layers/civic-ui/app/components/CivicDisclosurePanel.vue";

describe("CivicDisclosurePanel", () => {
  it("keeps native disclosure semantics and forwards standard attributes", async () => {
    const wrapper = mount(CivicDisclosurePanel, {
      attrs: { id: "gender-panel" },
      props: { title: "Gender" },
      slots: { default: "<p>Filter options</p>" },
    });

    const disclosure = wrapper.get("details");
    const summary = disclosure.get("summary");

    expect(disclosure.attributes("id")).toBe("gender-panel");
    expect(summary.text()).toBe("Gender");
    expect(disclosure.get("p").text()).toBe("Filter options");
    expect((disclosure.element as HTMLDetailsElement).open).toBe(false);

    await summary.trigger("click");

    expect((disclosure.element as HTMLDetailsElement).open).toBe(true);
  });

  it("keeps an optional header action outside collapsed details content", () => {
    const wrapper = mount(CivicDisclosurePanel, {
      props: { title: "Gender" },
      slots: {
        action: '<button aria-label="Reset Gender filter">Reset</button>',
        default: "<p>Filter options</p>",
      },
    });

    const action = wrapper.get('button[aria-label="Reset Gender filter"]');
    expect(action.element.closest("details")).toBeNull();
    expect((wrapper.get("details").element as HTMLDetailsElement).open).toBe(
      false,
    );
  });
});
