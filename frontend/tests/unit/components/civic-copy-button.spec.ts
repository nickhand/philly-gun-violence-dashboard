import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import CivicCopyButton from "../../../layers/civic-ui/app/components/CivicCopyButton.vue";

function stubClipboard(writeText: (text: string) => Promise<void>): void {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
}

function stubExecCommand(copy: () => boolean): void {
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    value: vi.fn(copy),
  });
}

afterEach(() => {
  delete (navigator as unknown as { clipboard?: Clipboard }).clipboard;
  delete (
    document as unknown as {
      execCommand?: (command: string) => boolean;
    }
  ).execCommand;
  vi.restoreAllMocks();
});

describe("CivicCopyButton", () => {
  it("copies the supplied text and announces success", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    const wrapper = mount(CivicCopyButton, {
      props: {
        label: "Copy citation",
        text: "Philadelphia Gun Violence Dashboard citation",
      },
    });

    const button = wrapper.get("button");
    expect(button.attributes("type")).toBe("button");
    expect(button.classes()).toEqual(
      expect.arrayContaining(["usa-button", "usa-button--outline"]),
    );
    expect(button.text()).toBe("Copy citation");
    expect(wrapper.get('[role="status"]').attributes()).toMatchObject({
      "aria-atomic": "true",
      "aria-live": "polite",
    });

    await button.trigger("click");
    await flushPromises();

    expect(writeText).toHaveBeenCalledWith(
      "Philadelphia Gun Violence Dashboard citation",
    );
    expect(wrapper.get('[role="status"]').text()).toBe("Copied to clipboard.");
  });

  it("falls back to a temporary selection when the Clipboard API rejects", async () => {
    stubClipboard(vi.fn().mockRejectedValue(new Error("NotAllowedError")));
    let selectedText = "";
    stubExecCommand(() => {
      selectedText = document.querySelector("textarea")?.value ?? "";
      return true;
    });
    const wrapper = mount(CivicCopyButton, {
      attachTo: document.body,
      props: { text: "Citation to copy" },
    });
    const button = wrapper.get("button");
    button.element.focus();

    await button.trigger("click");
    await flushPromises();

    expect(document.execCommand).toHaveBeenCalledWith("copy");
    expect(selectedText).toBe("Citation to copy");
    expect(document.querySelector("textarea")).toBeNull();
    expect(document.activeElement).toBe(button.element);
    expect(wrapper.get('[role="status"]').text()).toBe("Copied to clipboard.");
    wrapper.unmount();
  });

  it("provides a manual-copy recovery message when copying fails", async () => {
    stubClipboard(vi.fn().mockRejectedValue(new Error("NotAllowedError")));
    stubExecCommand(() => false);
    const wrapper = mount(CivicCopyButton, {
      props: { label: "Copy citation", text: "Citation to copy" },
    });

    await wrapper.get("button").trigger("click");
    await flushPromises();

    const status = wrapper.get('[role="status"]');
    expect(status.text()).toBe(
      "Could not copy. Select and copy the text manually.",
    );
    expect(status.classes()).toContain("civic-copy-control__status--error");
    expect(wrapper.get("button").attributes("disabled")).toBeUndefined();
  });
});
