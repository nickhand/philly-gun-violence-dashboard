import "@mdi/font/css/materialdesignicons.css";
import "vuetify/styles";
import { createVuetify } from "vuetify";
import { aliases, mdi } from "vuetify/iconsets/mdi";

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
          error: "#d84545",
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
    aliases,
    sets: {
      mdi,
    },
  },
});
