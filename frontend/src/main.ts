import { createApp } from "vue";
import { createHead } from "@unhead/vue/client";
import App from "@/app/App.vue";
import { createAppRouter } from "@/app/router";
import { createAppPinia } from "@/app/pinia";
import { vuetify } from "@/app/vuetify";
import { initAnalytics } from "@/shared/analytics";

// Styles
import "@/app/styles/main.css";

// Initialize analytics before app mount
initAnalytics();

const app = createApp(App);
const head = createHead();

// Register core app services once.
app.use(head);
app.use(createAppPinia());
app.use(createAppRouter());
app.use(vuetify);

app.mount("#app");
