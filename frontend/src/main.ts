import { createApp } from "vue";
import { createHead } from "@unhead/vue/client";
import App from "@/app/App.vue";
import { createAppRouter } from "@/app/router";
import { createAppPinia } from "@/app/pinia";
import { vuetify } from "@/app/vuetify";

// Styles
import "@/app/styles/main.css";

const app = createApp(App);
const head = createHead();

// Register core app services once.
app.use(head);
app.use(createAppPinia());
app.use(createAppRouter());
app.use(vuetify);

app.mount("#app");
