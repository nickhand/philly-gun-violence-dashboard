import { createRouter, createWebHistory } from "vue-router";
import DashboardPage from "@/pages/DashboardPage.vue";
import AboutPage from "@/pages/AboutPage.vue";

export function createAppRouter() {
  return createRouter({
    history: createWebHistory(),
    routes: [
      {
        path: "/",
        component: DashboardPage,
      },
      {
        path: "/about",
        component: AboutPage,
      },
      {
        path: "/:selectedYear",
        // Preserve legacy URL style by converting to query params.
        redirect: (to) => {
          const yearParam = String(to.params.selectedYear);
          const year = yearParam === "all" ? "All Years" : yearParam;
          return { path: "/", query: { year } };
        },
      },
    ],
  });
}
