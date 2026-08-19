import { createSharedResponseHeaders } from "./config/responseHeaders";

const canonicalBasePath = "/philly-gun-violence-map/";
const defaultDownloadsBaseUrl = "https://d2cemhjkwenjmb.cloudfront.net";
const appBaseUrl = process.env.NUXT_APP_BASE_URL ?? canonicalBasePath;
const siteOrigin = (
  process.env.NUXT_PUBLIC_SITE_URL ?? "https://www.nickhand.dev"
).replace(/\/$/, "");
const canonicalBaseUrl =
  process.env.NUXT_PUBLIC_CANONICAL_BASE_URL ??
  `${siteOrigin}${appBaseUrl.replace(/\/$/, "")}`;
const indexable = process.env.NUXT_PUBLIC_INDEXABLE !== "false";
const dataRouteRules =
  process.env.NODE_ENV === "production"
    ? {
        "/": { swr: 300 },
        "/data": { swr: 300 },
        "/stats": { swr: 300 },
      }
    : {};
const sharedResponseHeaders = createSharedResponseHeaders({
  indexable,
  production: process.env.NODE_ENV === "production",
});

export default defineNuxtConfig({
  compatibilityDate: "2026-08-14",
  devtools: { enabled: process.env.NUXT_DEVTOOLS === "true" },
  extends: ["./layers/civic-ui"],
  css: ["~/assets/styles/dashboard.scss"],
  modules: ["@nuxtjs/sitemap"],
  site: {
    url: siteOrigin,
    name: "Philadelphia Gun Violence Dashboard",
  },
  sitemap: {
    zeroRuntime: true,
  },
  routeRules: {
    "/**": {
      headers: sharedResponseHeaders,
    },
    ...dataRouteRules,
  },
  nitro: {
    cloudflare: {
      // Keep deployment configuration explicit and reviewable at the project
      // root rather than generating a hidden Wrangler redirect file.
      deployConfig: false,
      nodeCompat: true,
    },
  },
  app: {
    baseURL: appBaseUrl,
    head: {
      htmlAttrs: { lang: "en" },
      meta: [
        { charset: "utf-8" },
        {
          name: "viewport",
          content: "width=device-width, initial-scale=1",
        },
        { name: "theme-color", content: "#353d42" },
      ],
    },
  },
  runtimeConfig: {
    public: {
      apiBaseUrl:
        process.env.NUXT_PUBLIC_API_BASE_URL ??
        "https://philly-gun-violence-dashboard-api.fly.dev",
      downloadsBaseUrl:
        process.env.NUXT_PUBLIC_DOWNLOADS_BASE_URL ?? defaultDownloadsBaseUrl,
      canonicalBaseUrl,
      indexable,
    },
  },
  typescript: {
    strict: true,
    typeCheck: true,
  },
});
