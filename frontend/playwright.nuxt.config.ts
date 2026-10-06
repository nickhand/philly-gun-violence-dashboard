import { defineConfig, devices } from "@playwright/test";

const appHost = "127.0.0.1";
const appPort = 4180;
const apiPort = 4181;
const basePath = "/philly-gun-violence-map/";
const appOrigin = `http://${appHost}:${appPort}`;
const apiOrigin = `http://${appHost}:${apiPort}`;
const baseURL = `${appOrigin}${basePath}`;
const crossBrowserCore = [
  "**/accessibility.spec.ts",
  "**/civic-components.spec.ts",
  "**/dashboard.spec.ts",
  "**/stats-mobile.spec.ts",
];
const webkitCore = [
  ...crossBrowserCore,
  "**/data-mobile-tables.spec.ts",
];
// Headless Firefox on GitHub's Ubuntu runner cannot create the WebGL context
// MapLibre requires, even with webgl.force-enabled. Chromium and WebKit retain
// the real-map coverage; Firefox still runs the non-map core smoke/a11y flows.
const firefoxNonPortable = /\b(?:pdf|print|prints)\b|@maplibre/i;
const webkitNonPortable = /\b(?:pdf|print|prints)\b|forced-color/i;

export default defineConfig({
  testDir: "./tests/e2e/nuxt",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [["line"], ["html", { open: "never", outputFolder: "playwright-report/nuxt" }]]
    : [["list"], ["html", { open: "never", outputFolder: "playwright-report/nuxt" }]],
  outputDir: "test-results/nuxt",
  expect: { timeout: 15_000 },
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      command: "node tests/e2e/support/nuxtApiFixture.mjs",
      url: `${apiOrigin}/health`,
      env: {
        NUXT_E2E_ALLOWED_ORIGIN: appOrigin,
        NUXT_E2E_API_PORT: String(apiPort),
      },
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: `npm run dev:nuxt -- --host ${appHost} --port ${appPort}`,
      url: baseURL,
      env: {
        NUXT_APP_BASE_URL: basePath,
        NUXT_IGNORE_LOCK: "1",
        NUXT_PUBLIC_API_BASE_URL: apiOrigin,
        NUXT_PUBLIC_DOWNLOADS_BASE_URL:
          "https://data.example.test/philly-shooting-records",
        NUXT_PUBLIC_INDEXABLE: "false",
        NUXT_TELEMETRY_DISABLED: "1",
      },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
  projects: [
    {
      name: "nuxt-chromium",
      testIgnore: "**/mobile.spec.ts",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "nuxt-mobile-chrome",
      testMatch: "**/mobile.spec.ts",
      use: { ...devices["Pixel 7"] },
    },
    {
      name: "nuxt-firefox-core",
      testMatch: crossBrowserCore,
      grepInvert: firefoxNonPortable,
      use: { ...devices["Desktop Firefox"] },
    },
    {
      name: "nuxt-webkit-core",
      testMatch: webkitCore,
      grepInvert: webkitNonPortable,
      use: { ...devices["Desktop Safari"] },
    },
    {
      name: "nuxt-mobile-webkit",
      testMatch: [
        "**/mobile.spec.ts",
        "**/data-mobile-tables.spec.ts",
        "**/stats-mobile.spec.ts",
      ],
      grepInvert: webkitNonPortable,
      use: { ...devices["iPhone 13"] },
    },
  ],
});
