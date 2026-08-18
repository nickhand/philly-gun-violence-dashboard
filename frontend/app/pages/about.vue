<script setup lang="ts">
const { canonicalBaseUrl } = useRuntimeConfig().public;
const siteUrl = String(canonicalBaseUrl).replace(/\/$/, "");

const canonicalUrl = `${siteUrl}/about`;
const description =
  "Purpose, stewardship, appropriate use, and corrections for the independent Philadelphia Gun Violence Dashboard.";

useSeoMeta({
  title: "About this project | Philadelphia Gun Violence Dashboard",
  description,
  ogType: "website",
  ogTitle: "About the Philadelphia Gun Violence Dashboard",
  ogDescription: description,
  ogUrl: canonicalUrl,
  ogImage: `${siteUrl}/og-image.png`,
  twitterCard: "summary_large_image",
  twitterTitle: "About the Philadelphia Gun Violence Dashboard",
  twitterDescription: description,
  twitterImage: `${siteUrl}/og-image.png`,
});

useHead({
  link: [{ rel: "canonical", href: canonicalUrl }],
});
</script>

<template>
  <main id="main-content" class="civic-reference-page" tabindex="-1">
    <header class="grid-container civic-container civic-page-intro">
      <h1>About this dashboard</h1>
      <p class="usa-intro">
        This independent project makes public Philadelphia shooting-victim
        records easier to explore, compare, and download.
      </p>
    </header>

    <div class="grid-container civic-container civic-content-section">
      <article class="usa-prose civic-prose">
        <section aria-labelledby="purpose">
          <h2 id="purpose">What the dashboard contains</h2>
          <p>
            Each record describes one person reported shot, not one shooting
            incident. The map and charts organize Philadelphia Police Department
            (PPD) records by date, location, fatal or nonfatal outcome, and
            reported demographics. The Statistics page separately reports PPD's
            count of all homicides citywide, whether or not a gun was involved.
          </p>
          <p>
            Use the <a :href="siteUrl">interactive dashboard</a> to examine the
            records, the <NuxtLink to="/stats">statistics page</NuxtLink> for
            current and annual counts, or the
            <NuxtLink to="/data">data guide</NuxtLink> for downloads and field
            definitions.
          </p>
        </section>

        <section class="civic-rule-section" aria-labelledby="ownership">
          <h2 id="ownership">Status and stewardship</h2>
          <p>
            <a href="https://www.nickhand.dev/" rel="author">Nick Hand</a>
            maintains the dashboard as an independent public project. The first
            version was developed at the Philadelphia City Controller’s Office.
            This is not an official City of Philadelphia website. The agencies
            that publish the underlying records remain the sources of record.
          </p>
        </section>

        <section class="civic-rule-section" aria-labelledby="appropriate-use">
          <h2 id="appropriate-use">What the records cannot show</h2>
          <p>
            These records can show reported patterns in time, place, outcome,
            and demographics. They cannot explain why a shooting happened or
            describe a person’s circumstances or conditions in a neighborhood.
            Review the original sources and methodology before drawing
            conclusions.
          </p>
        </section>

        <section class="civic-rule-section" aria-labelledby="corrections">
          <h2 id="corrections">Documentation and corrections</h2>
          <p>
            The <NuxtLink to="/methodology">methodology</NuxtLink> documents
            scope, transformations, checks, and limitations. The processing code
            and tests are available in the
            <a
              href="https://github.com/nickhand/philly-gun-violence-dashboard"
              rel="external"
            >
              public repository</a
            >.
          </p>
          <p>
            To report a possible data or documentation error,
            <a
              href="https://github.com/nickhand/philly-gun-violence-dashboard/issues/new"
              rel="external"
            >open a GitHub issue</a>. Include the affected record or page, a
            short description, and a supporting source when available. GitHub
            issues are public; do not include sensitive personal information.
          </p>
        </section>
      </article>
    </div>
  </main>
</template>
