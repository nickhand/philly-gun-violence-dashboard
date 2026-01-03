import Vue from "vue";
import Router from "vue-router";
import Dashboard from "@/views/Dashboard/index.vue";
import AboutPage from "@/views/About/index.vue";

Vue.use(Router);

export async function getRouter() {
  // Return the router
  return new Router({
    routes: [
      // About page
      {
        path: "/about",
        component: AboutPage,
        props: {},
      },
      // Dashboard page
      {
        path: "/",
        component: Dashboard,
        props: {},
      },
      // Redirect to dashboard with query params
      {
        path: "/:selectedYear",
        redirect: (to) => {
          let year;
          if (to.params.selectedYear == "all") year = "All Years";
          else year = to.params.selectedYear;

          return { path: "/", query: { year: year } };
        },
      },
    ],
  });
}
