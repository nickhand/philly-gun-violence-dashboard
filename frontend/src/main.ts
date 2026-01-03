// Local css first
import "@/assets/css/style.min.css";
import "@/assets/css/bootstrap.min.css";

// External
import Vue from "vue";

// App and router
import App from "@/App.vue";
import { getRouter } from "@/plugins/router";
import vuetify from "@/plugins/vuetify";
import store from "@/store";
import "@/main.css";

// Fontawesome
import { library } from "@fortawesome/fontawesome-svg-core";
import {
  faInfo,
  faArrowLeft,
  faDownload,
  faUndo,
  faExternalLinkAlt,
} from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";

// Set up fontawesome
library.add(faInfo, faArrowLeft, faDownload, faUndo, faExternalLinkAlt);
Vue.component("font-awesome-icon", FontAwesomeIcon);

// Don't show tip
Vue.config.productionTip = false;

// Initialize
getRouter().then((router) => {
  new Vue({
    router,
    vuetify,
    store,
    render: (h) => h(App),
  }).$mount("#app");
});

// Turn off FA
// $(document).ready(function () {
//   const FA = window.FontAwesome;
//   if (FA) {
//     FA.config.observeMutations = false;
//     FA.config.searchPseudoElements = false;
//   }
// });
