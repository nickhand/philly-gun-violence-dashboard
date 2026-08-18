<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const route = useRoute();
const header = ref<HTMLElement | null>(null);
const menuButton = ref<HTMLButtonElement | null>(null);
const menuOpen = ref(false);
const navigation = [
  { label: "Statistics", to: "/stats" },
  { label: "Data", to: "/data" },
  { label: "Methodology", to: "/methodology" },
  { label: "About", to: "/about" },
];

function normalizePath(path: string): string {
  return path.replace(/\/+$/, "") || "/";
}

function isCurrentPath(path: string): boolean {
  return normalizePath(route.path) === normalizePath(path);
}

function closeMenu(): void {
  menuOpen.value = false;
}

function toggleMenu(): void {
  menuOpen.value = !menuOpen.value;
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key !== "Escape" || !menuOpen.value) return;
  closeMenu();
  menuButton.value?.focus();
}

function handleOutsidePointer(event: PointerEvent): void {
  if (!menuOpen.value || header.value?.contains(event.target as Node)) return;
  closeMenu();
}

watch(() => route.path, closeMenu);

onMounted(() => {
  document.addEventListener("keydown", handleKeydown);
  document.addEventListener("pointerdown", handleOutsidePointer);
});

onBeforeUnmount(() => {
  document.removeEventListener("keydown", handleKeydown);
  document.removeEventListener("pointerdown", handleOutsidePointer);
});
</script>

<template>
  <a class="usa-skipnav" href="#main-content">Skip to main content</a>
  <header ref="header" class="civic-site-header">
    <div class="grid-container civic-container civic-site-header__inner">
      <NuxtLink
        to="/"
        class="civic-site-header__brand"
      >
        Philadelphia Gun Violence Dashboard
      </NuxtLink>

      <button
        ref="menuButton"
        class="usa-menu-btn civic-site-header__menu-button"
        type="button"
        aria-controls="primary-navigation"
        :aria-expanded="menuOpen"
        @click="toggleMenu"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24">
          <path d="M3 6h18v2H3zm0 5h18v2H3zm0 5h18v2H3z" />
        </svg>
        <span>Menu</span>
      </button>

      <nav
        id="primary-navigation"
        class="civic-site-header__navigation"
        :class="{ 'civic-site-header__navigation--open': menuOpen }"
        aria-label="Primary navigation"
      >
        <ul class="civic-site-header__nav">
          <li>
            <NuxtLink
              to="/"
              :class="{
                'civic-site-header__current': isCurrentPath('/'),
              }"
              :aria-current="isCurrentPath('/') ? 'page' : undefined"
              @click="closeMenu"
            >
              Explore
            </NuxtLink>
          </li>
          <li v-for="item in navigation" :key="item.to">
            <NuxtLink
              :to="item.to"
              :class="{
                'civic-site-header__current': isCurrentPath(item.to),
              }"
              :aria-current="isCurrentPath(item.to) ? 'page' : undefined"
              @click="closeMenu"
            >
              {{ item.label }}
            </NuxtLink>
          </li>
        </ul>
      </nav>
    </div>
  </header>
</template>
