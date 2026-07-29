<template>
  <div class="address-search" :class="{ 'address-search--open': showResults }">
    <div class="search-input-wrapper">
      <v-icon icon="$magnify" size="18" class="search-icon" />
      <input
        ref="inputRef"
        v-model="query"
        type="text"
        class="search-input"
        placeholder="Search address..."
        role="combobox"
        aria-label="Search for an address in Philadelphia"
        aria-autocomplete="list"
        :aria-expanded="showResults && results.length > 0"
        aria-controls="address-search-results"
        :aria-activedescendant="
          activeIndex >= 0 ? `address-search-result-${activeIndex}` : undefined
        "
        :aria-busy="isLoading"
        @input="handleInput"
        @focus="showResults = results.length > 0"
        @keydown.escape="handleEscape"
        @keydown.enter="handleEnter"
        @keydown.down.prevent="handleArrowDown"
        @keydown.up.prevent="handleArrowUp"
      />
      <button
        v-if="query"
        class="clear-button"
        type="button"
        aria-label="Clear search"
        @click="handleClear"
      >
        <v-icon icon="$close" size="16" />
      </button>
      <div v-if="isLoading" class="loading-indicator">
        <v-progress-circular
          indeterminate
          size="16"
          width="2"
          color="white"
          aria-label="Searching addresses"
        />
      </div>
    </div>

    <!-- Results dropdown -->
    <div
      v-if="showResults && results.length > 0"
      id="address-search-results"
      class="search-results"
      role="listbox"
      aria-label="Address search results"
    >
      <button
        v-for="(result, index) in results"
        :key="result.id"
        :id="`address-search-result-${index}`"
        class="search-result"
        :class="{ 'search-result--active': index === activeIndex }"
        role="option"
        tabindex="-1"
        :aria-selected="index === activeIndex"
        @click="handleSelect(result)"
        @mouseenter="activeIndex = index"
      >
        <v-icon icon="$mapMarker" size="16" class="result-icon" />
        <span class="result-text">{{ result.shortName }}</span>
      </button>
    </div>

    <!-- No results message -->
    <div
      v-else-if="
        showResults && query.length >= 3 && !isLoading && results.length === 0
      "
      class="search-no-results"
      role="status"
      aria-live="polite"
    >
      No addresses found in Philadelphia
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from "vue";
import {
  useGeocoding,
  type AddressResult,
} from "../../composables/useGeocoding";
import { track } from "@/shared/analytics";

const emit = defineEmits<{
  (e: "select", result: AddressResult): void;
  (e: "clear"): void;
}>();

const { results, isLoading, searchAddress, clearResults } = useGeocoding();

const inputRef = ref<HTMLInputElement | null>(null);
const query = ref("");
const showResults = ref(false);
const activeIndex = ref(-1);

// Debounce timer
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * Handle input with debounce.
 */
function handleInput(): void {
  if (debounceTimer) {
    clearTimeout(debounceTimer);
  }

  debounceTimer = setTimeout(() => {
    searchAddress(query.value);
    showResults.value = true;
    activeIndex.value = -1;
  }, 300);
}

/**
 * Handle selecting a result.
 */
function handleSelect(result: AddressResult): void {
  query.value = result.shortName;
  showResults.value = false;
  activeIndex.value = -1;

  // Track location search
  track("location_searched", {
    found: true,
  });

  emit("select", result);
}

/**
 * Handle clearing the search.
 */
function handleClear(): void {
  query.value = "";
  clearResults();
  showResults.value = false;
  activeIndex.value = -1;
  inputRef.value?.focus();
  emit("clear");
}

/**
 * Handle escape key.
 */
function handleEscape(): void {
  showResults.value = false;
  activeIndex.value = -1;
}

/**
 * Handle enter key to select active result.
 */
function handleEnter(): void {
  if (activeIndex.value >= 0 && activeIndex.value < results.value.length) {
    handleSelect(results.value[activeIndex.value]);
  }
}

/**
 * Handle arrow down key.
 */
function handleArrowDown(): void {
  if (!showResults.value && results.value.length > 0) {
    showResults.value = true;
  }
  if (activeIndex.value < results.value.length - 1) {
    activeIndex.value++;
  }
}

/**
 * Handle arrow up key.
 */
function handleArrowUp(): void {
  if (activeIndex.value > 0) {
    activeIndex.value--;
  }
}

/**
 * Close dropdown when clicking outside.
 */
function handleClickOutside(event: MouseEvent): void {
  const target = event.target as HTMLElement;
  if (!target.closest(".address-search")) {
    showResults.value = false;
  }
}

// Reset active index when results change
watch(results, () => {
  activeIndex.value = -1;
});

onMounted(() => {
  document.addEventListener("click", handleClickOutside);
});

onUnmounted(() => {
  document.removeEventListener("click", handleClickOutside);
  if (debounceTimer) {
    clearTimeout(debounceTimer);
  }
});

// Expose clear method so parent can reset the search
defineExpose({
  clear: handleClear,
});
</script>

<style scoped>
.address-search {
  position: relative;
  width: 280px;
  font-family:
    system-ui,
    -apple-system,
    sans-serif;
}

@media screen and (max-width: 767.98px) {
  .address-search {
    width: 200px;
  }
}

.search-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  background: rgba(40, 46, 51, 0.97);
  border: 2px solid rgba(122, 181, 229, 0.4);
  border-radius: 6px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.4);
  transition: all 0.2s ease;
}

.address-search--open .search-input-wrapper,
.search-input-wrapper:focus-within {
  border-color: rgba(122, 181, 229, 0.8);
  box-shadow:
    0 2px 16px rgba(122, 181, 229, 0.3),
    0 4px 12px rgba(0, 0, 0, 0.4);
}

.search-icon {
  position: absolute;
  left: 10px;
  color: #7ab5e5;
  pointer-events: none;
}

.search-input {
  width: 100%;
  padding: 10px 36px 10px 36px;
  background: transparent;
  border: none;
  color: white;
  font-size: 14px;
  outline: none;
}

.search-input::placeholder {
  color: rgba(255, 255, 255, 0.7);
}

.clear-button {
  position: absolute;
  right: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 4px;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  transition: all 0.15s ease;
}

.clear-button:hover {
  background: rgba(255, 255, 255, 0.1);
  color: white;
}

.loading-indicator {
  position: absolute;
  right: 8px;
}

.search-results {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: rgba(53, 61, 66, 0.98);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  overflow: hidden;
  z-index: 1000;
}

.search-result {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 12px;
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.85);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease;
}

.search-result:hover,
.search-result--active {
  background: rgba(122, 181, 229, 0.15);
}

.result-icon {
  color: #7ab5e5;
  flex-shrink: 0;
}

.result-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-no-results {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  padding: 12px;
  background: rgba(53, 61, 66, 0.98);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  color: rgba(255, 255, 255, 0.5);
  font-size: 13px;
  text-align: center;
  z-index: 1000;
}
</style>
