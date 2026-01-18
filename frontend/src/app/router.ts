import { createRouter, createWebHistory } from "vue-router";
import DashboardPage from "@/pages/DashboardPage.vue";

// Lazy-load About page for better initial bundle size
const AboutPage = () => import("@/pages/AboutPage.vue");

export function createAppRouter() {
  return createRouter({
    history: createWebHistory(import.meta.env.BASE_URL),
    routes: [
      {
        path: "/",
        component: DashboardPage,
      },
      {
        path: "/about",
        component: AboutPage,
      },
    ],
  });
}
