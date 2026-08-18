import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import CivicSelectField from "../../../layers/civic-ui/app/components/CivicSelectField.vue";

describe("CivicSelectField", () => {
  it("keeps native label, hint, selection, and option semantics", () => {
    const wrapper = mount(CivicSelectField, {
      props: {
        hint: "Choose a geography",
        id: "geography",
        label: "Choropleth layer",
        modelValue: "zip-codes",
        name: "geography",
        options: [
          { label: "None", value: "" },
          { label: "ZIP Codes", value: "zip-codes" },
          { disabled: true, label: "Unavailable", value: "unavailable" },
        ],
        tone: "inverse",
      },
    });

    const select = wrapper.get("select");
    const options = wrapper.findAll("option");

    expect(wrapper.get("label").attributes("for")).toBe("geography");
    expect(select.attributes()).toMatchObject({
      id: "geography",
      name: "geography",
      "aria-describedby": "geography-hint",
    });
    expect((select.element as HTMLSelectElement).value).toBe("zip-codes");
    expect(options[1].attributes("selected")).toBeUndefined();
    expect(options[2].attributes("disabled")).toBeDefined();
    expect(wrapper.get("#geography-hint").text()).toBe(
      "Choose a geography",
    );
  });

  it("emits the selected string value", async () => {
    const wrapper = mount(CivicSelectField, {
      props: {
        id: "year",
        label: "Year",
        modelValue: "2026",
        options: [
          { label: "2026", value: "2026" },
          { label: "All Years", value: "All Years" },
        ],
      },
    });

    await wrapper.get("select").setValue("All Years");

    expect(wrapper.emitted("update:modelValue")).toEqual([["All Years"]]);
  });

  it("keeps a clearable floating label out of the option list", async () => {
    const wrapper = mount(CivicSelectField, {
      attachTo: document.body,
      props: {
        clearable: true,
        floatingLabel: true,
        id: "geography",
        label: "Choropleth Layer",
        modelValue: "zip-codes",
        options: [
          { label: "Police Districts", value: "police-districts" },
          { label: "ZIP Codes", value: "zip-codes" },
        ],
        tone: "inverse",
      },
    });

    const select = wrapper.get("select");
    const label = wrapper.get('label[for="geography"]');

    expect(label.text()).toBe("Choropleth Layer");
    expect(
      wrapper
        .findAll("option:not([hidden])")
        .map((option) => option.text()),
    ).toEqual(["Police Districts", "ZIP Codes"]);
    expect(wrapper.find('option[value=""]').exists()).toBe(false);

    const clear = wrapper.get(
      'button[aria-label="Clear Choropleth Layer"]',
    );
    await clear.trigger("click");

    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual([""]);
    expect(document.activeElement).toBe(select.element);

    await wrapper.setProps({ modelValue: "" });
    expect((select.element as HTMLSelectElement).value).toBe("");
    expect((select.element as HTMLSelectElement).selectedIndex).toBe(-1);
    expect(
      wrapper.find('button[aria-label="Clear Choropleth Layer"]').exists(),
    ).toBe(false);

    wrapper.unmount();
  });

  it("forwards native attributes, descriptions, and listeners to the select", async () => {
    const handleBlur = vi.fn();
    const wrapper = mount(CivicSelectField, {
      attrs: {
        "aria-describedby": "validation-help",
        "aria-invalid": "true",
        "data-control": "geography",
        form: "map-options",
        onBlur: handleBlur,
        required: true,
      },
      props: {
        hint: "Choose a geography",
        id: "geography",
        label: "Geography",
        modelValue: "zip-codes",
        options: [{ label: "ZIP Codes", value: "zip-codes" }],
      },
    });

    const root = wrapper.get(".civic-select-field");
    const select = wrapper.get("select");

    expect(root.attributes("required")).toBeUndefined();
    expect(root.attributes("aria-invalid")).toBeUndefined();
    expect(select.attributes()).toMatchObject({
      "aria-describedby": "validation-help geography-hint",
      "aria-invalid": "true",
      "data-control": "geography",
      form: "map-options",
      required: "",
    });

    await select.trigger("blur");
    expect(handleBlur).toHaveBeenCalledOnce();
  });

  it("does not emit changes from a disabled select or clear control", async () => {
    const wrapper = mount(CivicSelectField, {
      props: {
        clearable: true,
        disabled: true,
        floatingLabel: true,
        id: "geography",
        label: "Choropleth Layer",
        modelValue: "zip-codes",
        options: [{ label: "ZIP Codes", value: "zip-codes" }],
        tone: "inverse",
      },
    });

    const select = wrapper.get("select");
    const clear = wrapper.get('button[aria-label="Clear Choropleth Layer"]');
    expect(select.attributes("disabled")).toBeDefined();
    expect(clear.attributes("disabled")).toBeDefined();

    await select.trigger("change");
    await clear.trigger("click");
    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
  });
});
