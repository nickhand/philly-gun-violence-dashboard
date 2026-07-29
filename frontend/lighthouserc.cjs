const { chromium } = require("@playwright/test");

module.exports = {
  ci: {
    collect: {
      chromePath: process.env.CHROME_PATH || chromium.executablePath(),
      startServerCommand: "node scripts/serve-lighthouse.mjs",
      startServerReadyPattern: "Lighthouse fixture server listening",
      startServerReadyTimeout: 20_000,
      url: ["http://127.0.0.1:4174/philly-gun-violence-map/"],
      numberOfRuns: 3,
      settings: {
        preset: "desktop",
        onlyCategories: [
          "performance",
          "accessibility",
          "best-practices",
          "seo",
        ],
        chromeFlags: "--no-sandbox --disable-dev-shm-usage",
      },
    },
    assert: {
      aggregationMethod: "median",
      assertions: {
        "categories:performance": ["error", { minScore: 0.8 }],
        "categories:accessibility": ["error", { minScore: 0.95 }],
        "categories:best-practices": ["error", { minScore: 0.9 }],
        "categories:seo": ["error", { minScore: 0.95 }],
        "largest-contentful-paint": [
          "error",
          { maxNumericValue: 2_500 },
        ],
        "cumulative-layout-shift": [
          "error",
          { maxNumericValue: 0.1 },
        ],
        "total-blocking-time": ["error", { maxNumericValue: 300 }],
      },
    },
    upload: {
      target: "filesystem",
      outputDir: "./lighthouse-report",
    },
  },
};
