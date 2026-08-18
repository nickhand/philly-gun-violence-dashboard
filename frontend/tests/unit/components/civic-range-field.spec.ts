import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import CivicRangeField from "../../../layers/civic-ui/app/components/CivicRangeField.vue";

describe("CivicRangeField", () => {
  it("associates its label and visible formatted value with the range", () => {
    const wrapper = mount(CivicRangeField, {
      props: {
        id: "opacity",
        modelValue: 0.5,
        label: "Opacity",
        min: 0,
        max: 0.5,
        step: 0.01,
        formatValue: (value: number) => `${Math.round(value * 100)}%`,
      },
    });

    const input = wrapper.get('input[type="range"]');
    const output = wrapper.get("output");

    expect(wrapper.get("label").attributes("for")).toBe("opacity");
    expect(input.attributes()).toMatchObject({
      id: "opacity",
      min: "0",
      max: "0.5",
      step: "0.01",
      "aria-valuetext": "50%",
    });
    expect(output.text()).toBe("50%");
    expect(output.attributes()).toMatchObject({
      for: "opacity",
      "aria-hidden": "true",
    });
  });

  it("emits numeric model updates while the slider moves", async () => {
    const wrapper = mount(CivicRangeField, {
      props: {
        modelValue: 25,
        label: "Coverage",
      },
    });

    await wrapper.get('input[type="range"]').setValue("40");

    expect(wrapper.emitted("update:modelValue")).toEqual([[40]]);
  });

  it("forwards native attributes and listeners to the range input", async () => {
    const handleBlur = vi.fn();
    const wrapper = mount(CivicRangeField, {
      attrs: {
        "aria-describedby": "coverage-help",
        "aria-invalid": "true",
        "data-control": "coverage",
        form: "map-options",
        name: "coverage",
        onBlur: handleBlur,
        required: true,
      },
      props: {
        id: "coverage",
        label: "Coverage",
        modelValue: 25,
      },
    });

    const root = wrapper.get(".civic-range-field");
    const input = wrapper.get('input[type="range"]');
    expect(root.attributes("required")).toBeUndefined();
    expect(root.attributes("aria-invalid")).toBeUndefined();
    expect(input.attributes()).toMatchObject({
      "aria-describedby": "coverage-help",
      "aria-invalid": "true",
      "data-control": "coverage",
      form: "map-options",
      name: "coverage",
      required: "",
    });

    await input.trigger("blur");
    expect(handleBlur).toHaveBeenCalledOnce();
  });

  it("does not emit updates while disabled", async () => {
    const wrapper = mount(CivicRangeField, {
      props: {
        disabled: true,
        label: "Coverage",
        modelValue: 25,
      },
    });

    const input = wrapper.get('input[type="range"]');
    expect(input.attributes("disabled")).toBeDefined();
    await input.setValue("40");
    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
  });
});
