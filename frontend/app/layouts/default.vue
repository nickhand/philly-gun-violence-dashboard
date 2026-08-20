<script setup lang="ts">
import {
  createDashboardIdentityEntities,
  getDashboardEntityIds,
} from "~/utils/structuredData";

const { canonicalBaseUrl: configuredCanonicalBaseUrl } =
  useRuntimeConfig().public;
const canonicalBaseUrl = String(configuredCanonicalBaseUrl).replace(
  /\/$/,
  "",
);
const entityIds = getDashboardEntityIds(canonicalBaseUrl);
const identityEntities = createDashboardIdentityEntities(entityIds);

useHead({
  script: identityEntities.map((entity) => ({
    type: "application/ld+json",
    innerHTML: JSON.stringify({
      "@context": "https://schema.org",
      ...entity,
    }).replace(/</g, "\\u003c"),
  })),
});
</script>

<template>
  <div class="civic-app-shell">
    <CivicSiteHeader />
    <slot />
    <CivicSiteFooter />
  </div>
</template>
