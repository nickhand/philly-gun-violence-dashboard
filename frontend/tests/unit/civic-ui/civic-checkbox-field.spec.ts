import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import CivicCheckboxField from "../../../layers/civic-ui/app/components/CivicCheckboxField.vue";

describe("CivicCheckboxField", () => {
  it("keeps a native checkbox and its visible label directly associated", () => {
    const wrapper = mount(CivicCheckboxField, {
      attrs: {
        "aria-describedby": "unknown-help",
        name: "exclude-unknown",
        required: true,
      },
      props: {
        id: "exclude-unknown",
        label: "Exclude unknown values",
        modelValue: true,
        tone: "inverse",
      },
    });

    const input = wrapper.get('input[type="checkbox"]');
    const label = wrapper.get("label");

    expect(wrapper.element.tagName).toBe("DIV");
    expect(wrapper.classes()).toEqual(
      expect.arrayContaining([
        "usa-checkbox",
        "civic-checkbox-field",
        "civic-checkbox-field--inverse",
      ]),
    );
    expect(input.attributes()).toMatchObject({
      id: "exclude-unknown",
      "aria-describedby": "unknown-help",
      name: "exclude-unknown",
      required: "",
    });
    expect((input.element as HTMLInputElement).checked).toBe(true);
    expect(label.attributes("for")).toBe("exclude-unknown");
    expect(label.text()).toBe("Exclude unknown values");
  });

  it("emits checked-state updates and forwards native listeners", async () => {
    const handleBlur = vi.fn();
    const wrapper = mount(CivicCheckboxField, {
      attrs: { onBlur: handleBlur },
      props: {
        id: "records",
        label: "Records",
        modelValue: false,
      },
    });
    const input = wrapper.get('input[type="checkbox"]');

    await input.setValue(true);
    await input.trigger("blur");

    expect(wrapper.emitted("update:modelValue")).toEqual([[true]]);
    expect(handleBlur).toHaveBeenCalledOnce();
  });

  it("keeps disabled state native and does not emit synthetic changes", async () => {
    const wrapper = mount(CivicCheckboxField, {
      props: {
        disabled: true,
        id: "disabled-records",
        label: "Records",
        modelValue: false,
      },
    });
    const input = wrapper.get('input[type="checkbox"]');

    expect(input.attributes("disabled")).toBeDefined();
    await input.setValue(true);
    await input.trigger("change");
    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
  });
});
