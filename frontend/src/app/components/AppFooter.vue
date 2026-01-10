<template>
  <footer class="app-footer">
    <p>
      Built in Wissahickon by
      <a
        href="https://nickhand.dev"
        target="_blank"
        rel="noopener noreferrer"
        class="footer-link"
      >
        Nick Hand
      </a>
      • {{ currentYear }}
    </p>
  </footer>
</template>

<script setup lang="ts">
/**
 * Shared footer component used across all pages.
 */
const currentYear = new Date().getFullYear();
</script>

<style scoped>
.app-footer {
  width: 100%;
  padding: 1.5rem 1rem;
  font-size: 0.9rem;
  text-align: center;
  color: rgba(var(--v-theme-primary), 0.7);
  background-color: rgb(var(--v-theme-background));
}

.footer-link {
  color: rgb(var(--v-theme-secondary));
  text-decoration: none;
  transition: color 0.2s ease;
}

.footer-link:hover {
  color: rgb(var(--v-theme-primary));
  text-decoration: underline;
}
</style>
