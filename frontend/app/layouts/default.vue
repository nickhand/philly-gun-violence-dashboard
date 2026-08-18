<script setup lang="ts">
const { canonicalBaseUrl: configuredCanonicalBaseUrl } =
  useRuntimeConfig().public;
const canonicalBaseUrl = String(configuredCanonicalBaseUrl).replace(
  /\/$/,
  "",
);

useHead({
  script: [
    {
      type: "application/ld+json",
      innerHTML: JSON.stringify({
        "@context": "https://schema.org",
        "@type": "WebSite",
        "@id": `${canonicalBaseUrl}#website`,
        name: "Philadelphia Gun Violence Dashboard",
        url: canonicalBaseUrl,
      }).replace(/</g, "\\u003c"),
    },
  ],
});
</script>

<template>
  <div class="civic-app-shell">
    <CivicSiteHeader />
    <slot />
    <CivicSiteFooter />
  </div>
</template>
