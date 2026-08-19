import assert from "node:assert/strict";
import test from "node:test";

import {
  evaluateLighthouseRuns,
  extractLighthouseMetrics,
  median,
} from "../scripts/lighthouse-policy.mjs";

function report({
  accessibility = 0.98,
  bestPractices = 0.95,
  cls = 0.05,
  lcp = 2_000,
  performance = 0.9,
  seo = 1,
  tbt = 150,
} = {}) {
  return {
    categories: {
      accessibility: { score: accessibility },
      "best-practices": { score: bestPractices },
      performance: { score: performance },
      seo: { score: seo },
    },
    audits: {
      "cumulative-layout-shift": { numericValue: cls },
      "largest-contentful-paint": { numericValue: lcp },
      "total-blocking-time": { numericValue: tbt },
    },
  };
}

test("median is order-independent and supports even sets", () => {
  assert.equal(median([3, 1, 2]), 2);
  assert.equal(median([4, 1, 3, 2]), 2.5);
});

test("extractLighthouseMetrics rejects incomplete reports", () => {
  assert.throws(
    () => extractLighthouseMetrics({ categories: {}, audits: {} }),
    /categories\.performance\.score must be a finite number/,
  );
});

test("three passing runs are evaluated by their medians", () => {
  const result = evaluateLighthouseRuns([
    report({ performance: 0.7, lcp: 3_000 }),
    report({ performance: 0.85, lcp: 2_400 }),
    report({ performance: 0.9, lcp: 2_000 }),
  ]);

  assert.equal(result.passed, true);
  assert.equal(result.medians.performance, 0.85);
  assert.equal(result.medians["largest-contentful-paint"], 2_400);
});

test("score and timing regressions produce actionable failures", () => {
  const failing = report({ accessibility: 0.9, tbt: 450 });
  const result = evaluateLighthouseRuns([failing, failing, report()]);

  assert.equal(result.passed, false);
  assert.match(result.failures.join("\n"), /accessibility median score/);
  assert.match(result.failures.join("\n"), /total-blocking-time median/);
});

test("a partial run set cannot silently pass", () => {
  assert.throws(
    () => evaluateLighthouseRuns([report(), report()]),
    /expected 3 Lighthouse runs, received 2/,
  );
});
