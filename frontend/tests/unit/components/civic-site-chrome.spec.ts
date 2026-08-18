import { mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, nextTick, reactive } from "vue";

import CivicSiteFooter from "../../../layers/civic-ui/app/components/CivicSiteFooter.vue";
import CivicSiteHeader from "../../../layers/civic-ui/app/components/CivicSiteHeader.vue";

const NuxtLinkStub = defineComponent({
  name: "NuxtLink",
  inheritAttrs: false,
  props: {
    to: {
      type: String,
      required: true,
    },
  },
  setup(props, { attrs, slots }) {
    return () =>
      h("a", { ...attrs, href: props.to }, slots.default?.());
  },
});

const mountedWrappers: VueWrapper[] = [];

function track(wrapper: VueWrapper): VueWrapper {
  mountedWrappers.push(wrapper);
  return wrapper;
}

function mountHeader(path: string) {
  const route = reactive({ path });
  vi.stubGlobal("useRoute", () => route);
  const wrapper = track(
    mount(CivicSiteHeader, {
      attachTo: document.body,
      global: { stubs: { NuxtLink: NuxtLinkStub } },
    }),
  );
  return { route, wrapper };
}

afterEach(() => {
  for (const wrapper of mountedWrappers.splice(0)) wrapper.unmount();
  vi.unstubAllGlobals();
});

describe("CivicSiteHeader", () => {
  it("marks the trailing-slash route as the current navigation page", () => {
    const { wrapper } = mountHeader("/stats/");
    const links = wrapper
      .get('nav[aria-label="Primary navigation"]')
      .findAll("a");

    expect(links.map((link) => link.text())).toEqual([
      "Explore",
      "Statistics",
      "Data",
      "Methodology",
      "About",
    ]);
    expect(links[0].attributes("aria-current")).toBeUndefined();
    expect(links[1].attributes("aria-current")).toBe("page");
    expect(links[1].classes()).toContain("civic-site-header__current");
    expect(
      links.filter((link) => link.attributes("aria-current") === "page"),
    ).toHaveLength(1);
  });

  it("opens and closes the menu and resets it when the route changes", async () => {
    const { route, wrapper } = mountHeader("/");
    const button = wrapper.get('button[aria-controls="primary-navigation"]');
    const navigation = wrapper.get("#primary-navigation");

    expect(button.attributes("aria-expanded")).toBe("false");
    expect(navigation.classes()).not.toContain(
      "civic-site-header__navigation--open",
    );

    await button.trigger("click");
    expect(button.attributes("aria-expanded")).toBe("true");
    expect(navigation.classes()).toContain(
      "civic-site-header__navigation--open",
    );

    document.dispatchEvent(
      new KeyboardEvent("keydown", { bubbles: true, key: "Escape" }),
    );
    await nextTick();
    expect(button.attributes("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(button.element);

    await button.trigger("click");
    route.path = "/data/";
    await nextTick();
    expect(button.attributes("aria-expanded")).toBe("false");
    expect(
      wrapper
        .get('nav[aria-label="Primary navigation"]')
        .findAll("a")[2]
        .attributes("aria-current"),
    ).toBe("page");
  });
});

describe("CivicSiteFooter", () => {
  it("exposes concise project-navigation and source-code links", () => {
    const wrapper = track(
      mount(CivicSiteFooter, {
        global: { stubs: { NuxtLink: NuxtLinkStub } },
      }),
    );
    const links = wrapper
      .get('nav[aria-label="Project information"]')
      .findAll("a");

    expect(links.map((link) => link.text())).toEqual([
      "Data sources",
      "Methodology",
      "Corrections",
      "Source code",
    ]);
    expect(links.map((link) => link.attributes("href"))).toEqual([
      "/data#source-records",
      "/methodology",
      "/about#corrections",
      "https://github.com/nickhand/philly-gun-violence-dashboard",
    ]);
    expect(links[3].attributes("rel")).toBe("external");
  });
});
