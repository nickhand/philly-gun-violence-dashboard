export const LIGHTHOUSE_POLICY = Object.freeze({
  numberOfRuns: 3,
  minimumScores: Object.freeze({
    performance: 0.8,
    accessibility: 0.95,
    "best-practices": 0.9,
    seo: 0.95,
  }),
  maximumMetrics: Object.freeze({
    "largest-contentful-paint": 2_500,
    "cumulative-layout-shift": 0.1,
    "total-blocking-time": 300,
  }),
});

function requireFiniteNumber(value, label) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TypeError(`${label} must be a finite number`);
  }
  return value;
}

export function median(values) {
  if (!Array.isArray(values) || values.length === 0) {
    throw new TypeError("median requires at least one value");
  }

  const sorted = values
    .map((value, index) => requireFiniteNumber(value, `values[${index}]`))
    .sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);

  if (sorted.length % 2 === 1) {
    return sorted[middle];
  }
  return (sorted[middle - 1] + sorted[middle]) / 2;
}

export function extractLighthouseMetrics(lhr) {
  if (lhr?.runtimeError) {
    const code = lhr.runtimeError.code ?? "unknown";
    const message = lhr.runtimeError.message ?? "Lighthouse runtime error";
    throw new Error(`${code}: ${message}`);
  }

  const metrics = {};
  for (const category of Object.keys(LIGHTHOUSE_POLICY.minimumScores)) {
    metrics[category] = requireFiniteNumber(
      lhr?.categories?.[category]?.score,
      `categories.${category}.score`,
    );
  }
  for (const audit of Object.keys(LIGHTHOUSE_POLICY.maximumMetrics)) {
    metrics[audit] = requireFiniteNumber(
      lhr?.audits?.[audit]?.numericValue,
      `audits.${audit}.numericValue`,
    );
  }

  return metrics;
}

export function evaluateLighthouseRuns(
  lhrs,
  policy = LIGHTHOUSE_POLICY,
) {
  if (!Array.isArray(lhrs) || lhrs.length !== policy.numberOfRuns) {
    throw new Error(
      `expected ${policy.numberOfRuns} Lighthouse runs, received ${lhrs?.length ?? 0}`,
    );
  }

  const runs = lhrs.map(extractLighthouseMetrics);
  const medians = {};
  const failures = [];

  for (const [category, minimum] of Object.entries(policy.minimumScores)) {
    const value = median(runs.map((run) => run[category]));
    medians[category] = value;
    if (value < minimum) {
      failures.push(
        `${category} median score ${value.toFixed(3)} is below ${minimum.toFixed(3)}`,
      );
    }
  }

  for (const [audit, maximum] of Object.entries(policy.maximumMetrics)) {
    const value = median(runs.map((run) => run[audit]));
    medians[audit] = value;
    if (value > maximum) {
      failures.push(
        `${audit} median ${value.toFixed(3)} exceeds ${maximum.toFixed(3)}`,
      );
    }
  }

  return {
    failures,
    medians,
    passed: failures.length === 0,
    runs,
  };
}
