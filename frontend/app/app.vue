<script setup lang="ts">
import { nextTick, onBeforeUnmount, watch } from "vue";

const { canonicalBaseUrl, indexable } = useRuntimeConfig().public;
const route = useRoute();
let focusFrame: number | null = null;

const llmsGuideUrl = `${String(canonicalBaseUrl).replace(/\/$/, "")}/llms.txt`;

watch(
  () => route.path,
  async (path, previousPath) => {
    if (!import.meta.client || path === previousPath) return;
    await nextTick();
    if (focusFrame !== null) window.cancelAnimationFrame(focusFrame);
    focusFrame = window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>("#main-content")?.focus();
      focusFrame = null;
    });
  },
  { flush: "post" },
);

onBeforeUnmount(() => {
  if (focusFrame !== null) window.cancelAnimationFrame(focusFrame);
});

useSeoMeta({
  robots: () =>
    String(indexable) === "false"
      ? "noindex, nofollow"
      : "index, follow",
});

// unhead 3 only types well-known `rel` values. Its identity `defineLink`
// helper is not auto-imported, so assert the custom rel's shape here.
type HeadLinks = Extract<
  Parameters<typeof useHead>[0],
  { link?: unknown }
>["link"];

useHead({
  link: [
    {
      rel: "describedby",
      href: llmsGuideUrl,
      type: "text/plain",
    },
  ] as unknown as HeadLinks,
});
</script>

<template>
  <NuxtRouteAnnouncer />
  <NuxtLayout>
    <NuxtPage />
  </NuxtLayout>
</template>
