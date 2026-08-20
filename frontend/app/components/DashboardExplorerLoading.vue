<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  year: number | null;
}>();

const yearLabel = computed(() => props.year ?? "all years");
</script>

<template>
  <div
    class="civic-dashboard-map-filter-stage civic-dashboard-explorer-loading"
    aria-busy="true"
  >
    <div
      class="civic-legacy-map-explorer civic-legacy-map-explorer--fallback"
    >
      <div class="civic-legacy-map-view civic-dashboard-explorer-loading__map">
        <div class="civic-dashboard-explorer-loading__feedback">
          <div
            class="civic-dashboard-explorer-loading__progress"
            role="status"
            aria-live="polite"
          >
            <span
              class="civic-dashboard-explorer-loading__spinner"
              aria-hidden="true"
            ></span>
            <span>
              Loading {{ yearLabel }} record filters and locations…
            </span>
          </div>
          <strong>Explore shooting-victim records on a map.</strong>
          <span>
            The interactive view maps available locations and lets you filter
            records by date, reported demographics, outcome, and other fields.
          </span>
          <NuxtLink to="/data">View data and download records</NuxtLink>
        </div>
      </div>

      <aside
        id="filters"
        class="civic-legacy-sidebar civic-dashboard-explorer-loading__sidebar"
        aria-label="Map filters loading"
        tabindex="-1"
      >
        <span class="usa-sr-only">Map filters are loading.</span>
        <div
          class="civic-dashboard-explorer-loading__sidebar-inner"
          aria-hidden="true"
          inert
        >
          <div class="civic-dashboard-explorer-loading__header">
            <span class="civic-dashboard-explorer-loading__line is-wide"></span>
            <span class="civic-dashboard-explorer-loading__line is-medium"></span>
            <span class="civic-dashboard-explorer-loading__button"></span>
            <span class="civic-dashboard-explorer-loading__button"></span>
          </div>

          <div class="civic-dashboard-explorer-loading__sections">
            <section v-for="section in 5" :key="section">
              <span
                class="civic-dashboard-explorer-loading__line is-heading"
              ></span>
              <span class="civic-dashboard-explorer-loading__rule"></span>
              <span class="civic-dashboard-explorer-loading__field"></span>
              <span
                v-if="section < 3"
                class="civic-dashboard-explorer-loading__field is-short"
              ></span>
            </section>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.civic-dashboard-map-filter-stage {
  width: 100%;
}

.civic-dashboard-explorer-loading__map {
  display: grid;
  place-items: center;
  background:
    radial-gradient(circle at 35% 40%, rgba(122, 181, 229, 0.08), transparent 30%),
    #1d2224;
}

.civic-dashboard-explorer-loading__feedback {
  display: flex;
  max-width: 32rem;
  padding: 2rem;
  animation: dashboard-loading-reveal 180ms ease-out 120ms both;
  color: rgba(255, 255, 255, 0.82);
  flex-direction: column;
  gap: 0.75rem;
  align-items: center;
  line-height: 1.5;
  text-align: center;
}

.civic-dashboard-explorer-loading__feedback strong {
  color: #ffffff;
  font-weight: 600;
}

.civic-dashboard-explorer-loading__feedback a {
  color: #9dcbef;
  font-weight: 600;
}

.civic-dashboard-explorer-loading__progress {
  display: flex;
  margin-bottom: 0.5rem;
  flex-direction: column;
  gap: 0.75rem;
  align-items: center;
}

.civic-dashboard-explorer-loading__spinner {
  width: 2.25rem;
  height: 2.25rem;
  border: 3px solid rgba(255, 255, 255, 0.2);
  border-top-color: #7ab5e5;
  border-radius: 50%;
  animation: dashboard-loading-spin 900ms linear infinite;
}

.civic-dashboard-explorer-loading__sidebar {
  overflow: hidden;
}

.civic-dashboard-explorer-loading__sidebar-inner {
  width: 100%;
  animation: dashboard-loading-reveal 180ms ease-out 120ms both;
}

.civic-dashboard-explorer-loading__header,
.civic-dashboard-explorer-loading__sections {
  display: flex;
  flex-direction: column;
}

.civic-dashboard-explorer-loading__header {
  padding: 1.25rem 1.5rem 1.5rem;
  border-bottom: 5px solid #868b8e;
  gap: 0.75rem;
  align-items: center;
}

.civic-dashboard-explorer-loading__sections {
  padding: 1.25rem 1.5rem 3rem;
  gap: 1.75rem;
}

.civic-dashboard-explorer-loading__sections section {
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}

.civic-dashboard-explorer-loading__line,
.civic-dashboard-explorer-loading__button,
.civic-dashboard-explorer-loading__field,
.civic-dashboard-explorer-loading__rule {
  display: block;
  background: rgba(255, 255, 255, 0.13);
}

.civic-dashboard-explorer-loading__line {
  width: 58%;
  height: 0.85rem;
  border-radius: 999px;
}

.civic-dashboard-explorer-loading__line.is-wide {
  width: 82%;
}

.civic-dashboard-explorer-loading__line.is-medium {
  width: 66%;
}

.civic-dashboard-explorer-loading__line.is-heading {
  width: 42%;
  height: 1rem;
}

.civic-dashboard-explorer-loading__button,
.civic-dashboard-explorer-loading__field {
  width: 100%;
  height: 2.65rem;
  border-radius: 0.2rem;
}

.civic-dashboard-explorer-loading__field.is-short {
  width: 72%;
}

.civic-dashboard-explorer-loading__rule {
  width: 100%;
  height: 1px;
}

@keyframes dashboard-loading-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes dashboard-loading-reveal {
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .civic-dashboard-explorer-loading__feedback,
  .civic-dashboard-explorer-loading__sidebar-inner,
  .civic-dashboard-explorer-loading__spinner {
    animation: none;
  }
}
</style>
