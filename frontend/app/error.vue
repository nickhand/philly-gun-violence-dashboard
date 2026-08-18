<script setup lang="ts">
import type { NuxtError } from "#app";

const props = defineProps<{
  error: NuxtError;
}>();

const { canonicalBaseUrl: configuredCanonicalBaseUrl } =
  useRuntimeConfig().public;
const canonicalBaseUrl = String(configuredCanonicalBaseUrl).replace(
  /\/$/,
  "",
);
const isNotFound = computed(() => Number(props.error.statusCode) === 404);

useSeoMeta({
  title: () =>
    isNotFound.value
      ? "Page not found | Philadelphia Gun Violence Dashboard"
      : "Unable to load page | Philadelphia Gun Violence Dashboard",
  description: () =>
    isNotFound.value
      ? "The requested Philadelphia Gun Violence Dashboard page could not be found."
      : "The Philadelphia Gun Violence Dashboard could not load this page.",
  robots: "noindex, nofollow",
});
</script>

<template>
  <NuxtLayout>
    <main id="main-content" tabindex="-1">
      <header class="grid-container civic-container civic-page-intro">
        <p class="civic-page-intro__status">
          Error {{ error.statusCode }}
        </p>
        <h1>{{ isNotFound ? "Page not found" : "This page could not be loaded" }}</h1>
        <p class="usa-intro">
          <template v-if="isNotFound">
            The address may be incorrect, or the page may have moved.
          </template>
          <template v-else>
            The problem may be temporary. You can return to the dashboard or
            try another page.
          </template>
        </p>
        <ul class="usa-button-group">
          <li class="usa-button-group__item">
            <a class="usa-button" :href="canonicalBaseUrl">Return to dashboard</a>
          </li>
          <li class="usa-button-group__item">
            <NuxtLink class="usa-button usa-button--outline" to="/about">
              About this project
            </NuxtLink>
          </li>
        </ul>
      </header>
    </main>
  </NuxtLayout>
</template>
