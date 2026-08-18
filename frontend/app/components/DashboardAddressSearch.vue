<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

import {
  searchPhiladelphiaAddresses,
  type AddressResult,
} from "~/utils/geocoding";

const props = defineProps<{ resetKey: number }>();
const emit = defineEmits<{
  clear: [];
  select: [result: AddressResult];
}>();

const root = ref<HTMLDivElement | null>(null);
const input = ref<HTMLInputElement | null>(null);
const query = ref("");
const results = ref<AddressResult[]>([]);
const activeIndex = ref(-1);
const open = ref(false);
const state = ref<"idle" | "loading" | "error">("idle");
let debounceTimer: ReturnType<typeof setTimeout> | null = null;
let rateLimitTimer: ReturnType<typeof setTimeout> | null = null;
let releaseRateLimit: (() => void) | null = null;
let controller: AbortController | null = null;
let lastRequestAt = 0;
let searchId = 0;

function cancelSearch(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  if (rateLimitTimer) {
    clearTimeout(rateLimitTimer);
    releaseRateLimit?.();
  }
  debounceTimer = null;
  rateLimitTimer = null;
  releaseRateLimit = null;
  controller?.abort();
  controller = null;
}

async function search(value: string, currentSearchId: number): Promise<void> {
  const wait = Math.max(0, 1_000 - (Date.now() - lastRequestAt));
  if (wait > 0) {
    await new Promise<void>((resolve) => {
      releaseRateLimit = resolve;
      rateLimitTimer = setTimeout(() => {
        rateLimitTimer = null;
        releaseRateLimit = null;
        resolve();
      }, wait);
    });
  }
  if (currentSearchId !== searchId) return;

  const currentController = new AbortController();
  controller = currentController;
  state.value = "loading";
  open.value = true;
  lastRequestAt = Date.now();
  try {
    const found = await searchPhiladelphiaAddresses(value, {
      signal: currentController.signal,
    });
    if (currentSearchId !== searchId) return;
    results.value = found;
    activeIndex.value = -1;
    state.value = "idle";
  } catch (error) {
    if (
      currentSearchId === searchId &&
      (error as { name?: string } | null)?.name !== "AbortError"
    ) {
      results.value = [];
      state.value = "error";
    }
  } finally {
    if (controller === currentController) controller = null;
  }
}

function handleInput(): void {
  const currentSearchId = ++searchId;
  cancelSearch();
  activeIndex.value = -1;
  const value = query.value.trim();
  if (value.length < 3) {
    results.value = [];
    state.value = "idle";
    open.value = false;
    return;
  }
  debounceTimer = setTimeout(() => {
    debounceTimer = null;
    void search(value, currentSearchId);
  }, 300);
}

function selectResult(result: AddressResult): void {
  query.value = result.shortName;
  results.value = [];
  activeIndex.value = -1;
  open.value = false;
  emit("select", result);
}

function clear(focus = true): void {
  searchId += 1;
  cancelSearch();
  query.value = "";
  results.value = [];
  activeIndex.value = -1;
  open.value = false;
  state.value = "idle";
  if (focus) input.value?.focus();
  emit("clear");
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    open.value = false;
    activeIndex.value = -1;
    return;
  }
  if (event.key === "ArrowDown") {
    event.preventDefault();
    open.value = results.value.length > 0;
    activeIndex.value = Math.min(activeIndex.value + 1, results.value.length - 1);
    return;
  }
  if (event.key === "ArrowUp") {
    event.preventDefault();
    activeIndex.value = Math.max(activeIndex.value - 1, 0);
    return;
  }
  if (event.key === "Enter" && activeIndex.value >= 0) {
    event.preventDefault();
    const result = results.value[activeIndex.value];
    if (result) selectResult(result);
  }
}

function handleDocumentClick(event: MouseEvent): void {
  if (!root.value?.contains(event.target as Node)) open.value = false;
}

watch(
  () => props.resetKey,
  () => clear(false),
);

onMounted(() => document.addEventListener("click", handleDocumentClick));
onBeforeUnmount(() => {
  cancelSearch();
  document.removeEventListener("click", handleDocumentClick);
});
</script>

<template>
  <div
    ref="root"
    class="civic-dashboard-address-search civic-dashboard-address-search--overlay"
  >
    <div class="civic-dashboard-address-search__input">
      <svg
        class="civic-dashboard-address-search__icon"
        viewBox="0 0 24 24"
        aria-hidden="true"
        focusable="false"
      >
        <path
          d="m20.4 19-4.8-4.8a7 7 0 1 0-1.4 1.4l4.8 4.8a1 1 0 0 0 1.4-1.4ZM5 10a5 5 0 1 1 10 0 5 5 0 0 1-10 0Z"
        />
      </svg>
      <input
        id="dashboard-address-search"
        ref="input"
        v-model="query"
        class="usa-input"
        type="search"
        role="combobox"
        autocomplete="off"
        placeholder="Search address..."
        aria-label="Search for an address in Philadelphia"
        aria-autocomplete="list"
        aria-controls="dashboard-address-results"
        :aria-activedescendant="
          activeIndex >= 0 ? `dashboard-address-result-${activeIndex}` : undefined
        "
        :aria-busy="state === 'loading'"
        :aria-expanded="open && results.length > 0"
        @focus="open = results.length > 0"
        @input="handleInput"
        @keydown="handleKeydown"
      />
      <button
        v-if="query && state !== 'loading'"
        class="civic-dashboard-address-search__clear"
        type="button"
        aria-label="Clear search"
        @click="clear()"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <path
            d="M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z"
          />
        </svg>
      </button>
      <span
        v-if="state === 'loading'"
        class="civic-dashboard-address-search__loading"
        aria-hidden="true"
      >
        <svg viewBox="0 0 24 24" focusable="false">
          <path d="M12,4V2A10,10 0 0,0 2,12H4A8,8 0 0,1 12,4Z" />
        </svg>
      </span>
    </div>

    <ul
      v-if="open && results.length > 0"
      id="dashboard-address-results"
      class="civic-dashboard-address-search__results"
      role="listbox"
      aria-label="Address search results"
    >
      <li v-for="(result, index) in results" :key="result.id">
        <button
          :id="`dashboard-address-result-${index}`"
          type="button"
          role="option"
          tabindex="-1"
          :aria-selected="activeIndex === index"
          :class="{ 'is-active': activeIndex === index }"
          @click="selectResult(result)"
          @mouseenter="activeIndex = index"
        >
          <svg
            class="civic-dashboard-address-search__result-icon"
            viewBox="0 0 24 24"
            aria-hidden="true"
            focusable="false"
          >
            <path
              d="M12,11.5A2.5,2.5 0 0,1 9.5,9A2.5,2.5 0 0,1 12,6.5A2.5,2.5 0 0,1 14.5,9A2.5,2.5 0 0,1 12,11.5M12,2A7,7 0 0,0 5,9C5,14.25 12,22 12,22C12,22 19,14.25 19,9A7,7 0 0,0 12,2Z"
            />
          </svg>
          <span class="civic-dashboard-address-search__result-text">
            {{ result.shortName }}
          </span>
        </button>
      </li>
    </ul>
    <p
      v-if="state === 'loading'"
      class="usa-sr-only"
      role="status"
    >
      Searching addresses…
    </p>
    <p
      v-else-if="open && state === 'error'"
      class="civic-dashboard-address-search__status"
      role="status"
    >
      Address search is temporarily unavailable.
    </p>
    <p
      v-else-if="open && results.length === 0 && query.trim().length >= 3"
      class="civic-dashboard-address-search__status"
      role="status"
    >
      No addresses found in Philadelphia
    </p>
  </div>
</template>

<style scoped>
.civic-dashboard-address-search--overlay {
  width: 280px;
  max-width: calc(100vw - 20px);
  padding: 0;
  border: 0;
  background: transparent;
}

.civic-dashboard-address-search--overlay
  .civic-dashboard-address-search__input {
  border: 2px solid rgba(122, 181, 229, 0.4);
  border-radius: 0.375rem;
  background: rgba(40, 46, 51, 0.97);
  box-shadow: 0 0.125rem 0.75rem rgba(0, 0, 0, 0.4);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.civic-dashboard-address-search--overlay
  .civic-dashboard-address-search__input:focus-within {
  border-color: rgba(122, 181, 229, 0.8);
  box-shadow:
    0 0.125rem 1rem rgba(122, 181, 229, 0.3),
    0 0.25rem 0.75rem rgba(0, 0, 0, 0.4);
}

.civic-dashboard-address-search--overlay
  .civic-dashboard-address-search__icon {
  position: absolute;
  z-index: 1;
  top: 50%;
  left: 10px;
  width: 1rem;
  height: 1rem;
  transform: translateY(-50%);
  fill: #7ab5e5;
}

.civic-dashboard-address-search--overlay .usa-input {
  height: 41px;
  margin: 0;
  padding: 10px 36px;
  border: 0;
  color: #ffffff;
  background: transparent;
  font-size: 14px;
  line-height: 1.5;
}

.civic-dashboard-address-search .usa-input::-webkit-search-cancel-button {
  display: none;
  appearance: none;
}

.civic-dashboard-address-search .usa-input::-ms-clear {
  display: none;
}

.civic-dashboard-address-search--overlay .usa-input::placeholder {
  color: rgba(255, 255, 255, 0.72);
}

.civic-dashboard-address-search--overlay
  .civic-dashboard-address-search__clear {
  display: flex;
  width: 36px;
  height: 36px;
  min-width: 36px;
  min-height: 36px;
  padding: 0;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.5);
  background: transparent;
}

.civic-dashboard-address-search--overlay
  .civic-dashboard-address-search__clear:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.1);
}

.civic-dashboard-address-search__clear svg,
.civic-dashboard-address-search__loading,
.civic-dashboard-address-search__loading svg,
.civic-dashboard-address-search__result-icon {
  width: 1rem;
  height: 1rem;
  flex: 0 0 1rem;
  fill: currentColor;
}

.civic-dashboard-address-search__loading {
  position: absolute;
  z-index: 2;
  top: 50%;
  right: 8px;
  transform: translateY(-50%);
  color: #ffffff;
  animation: civic-address-search-spin 0.8s linear infinite;
}

@keyframes civic-address-search-spin {
  to {
    transform: translateY(-50%) rotate(360deg);
  }
}

.civic-dashboard-address-search--overlay
  .civic-dashboard-address-search__results,
.civic-dashboard-address-search--overlay
  .civic-dashboard-address-search__status {
  top: 100%;
  right: 0;
  left: 0;
}

.civic-dashboard-address-search--overlay
  .civic-dashboard-address-search__results {
  z-index: 1000;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  background: rgba(53, 61, 66, 0.98);
}

.civic-dashboard-address-search--overlay
  .civic-dashboard-address-search__results button {
  display: flex;
  min-height: 0;
  padding: 10px 12px;
  gap: 8px;
  align-items: center;
  color: rgba(255, 255, 255, 0.85);
  font-size: 13px;
}

.civic-dashboard-address-search__result-icon {
  color: #7ab5e5;
}

.civic-dashboard-address-search__result-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.civic-dashboard-address-search--overlay
  .civic-dashboard-address-search__status {
  position: absolute;
  z-index: 20;
  margin-top: 0.25rem;
  padding: 0.65rem 0.75rem;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  color: rgba(255, 255, 255, 0.5);
  background: rgba(53, 61, 66, 0.98);
  font-size: 13px;
  box-shadow: 0 0.5rem 1rem rgba(0, 0, 0, 0.35);
}

@media (max-width: 47.99em) {
  .civic-dashboard-address-search--overlay {
    width: 200px;
    max-width: calc(100vw - 10px);
  }
}
</style>
