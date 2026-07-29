import "vuetify/styles";
import { createVuetify } from "vuetify";
import { aliases, mdi } from "vuetify/iconsets/mdi-svg";
import {
  mdiAlertCircleOutline,
  mdiArrowLeft,
  mdiArrowRight,
  mdiClipboardTextOutline,
  mdiClose,
  mdiDatabase,
  mdiDatabaseOutline,
  mdiDownload,
  mdiEmail,
  mdiEmailOutline,
  mdiFileDelimited,
  mdiFilter,
  mdiGithub,
  mdiInformationOutline,
  mdiMagnify,
  mdiMapMarker,
  mdiRefresh,
  mdiUpdate,
  mdiWeb,
} from "@mdi/js";

export const vuetify = createVuetify({
  theme: {
    defaultTheme: "dark",
    themes: {
      dark: {
        dark: true,
        colors: {
          background: "#353d42",
          surface: "#353d42",
          primary: "#fff",
          secondary: "#b2beb5",
          error: "#ff8a8a",
          warning: "#e5dc8e",
          info: "#2196F3",
          success: "#4CAF50",
        },
      },
    },
  },
  defaults: {
    global: {
      // Use app font family for all Vuetify components
      style: "font-family: Avenir, Helvetica, Arial, sans-serif;",
    },
  },
  icons: {
    defaultSet: "mdi",
    aliases: {
      ...aliases,
      alertCircleOutline: mdiAlertCircleOutline,
      arrowLeft: mdiArrowLeft,
      arrowRight: mdiArrowRight,
      clipboardTextOutline: mdiClipboardTextOutline,
      close: mdiClose,
      database: mdiDatabase,
      databaseOutline: mdiDatabaseOutline,
      download: mdiDownload,
      email: mdiEmail,
      emailOutline: mdiEmailOutline,
      fileDelimited: mdiFileDelimited,
      filter: mdiFilter,
      github: mdiGithub,
      informationOutline: mdiInformationOutline,
      magnify: mdiMagnify,
      mapMarker: mdiMapMarker,
      refresh: mdiRefresh,
      update: mdiUpdate,
      web: mdiWeb,
    },
    sets: {
      mdi,
    },
  },
});
