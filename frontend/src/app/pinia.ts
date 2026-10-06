import { createPinia } from "pinia";

export function createAppPinia() {
  // Keep app-level Pinia creation in one place for future plugins.
  return createPinia();
}
