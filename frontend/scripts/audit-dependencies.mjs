// Fail on high/critical npm advisories, except a short, dated list of reviewed
// exceptions. Every exception needs a reason and expires; an expired exception
// fails the audit again so it cannot become permanent by accident.
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

export const EXCEPTIONS = [
  {
    id: 'GHSA-vfj7-8cjw-p6xm',
    package: 'braces',
    reviewed: '2026-10-05',
    expires: '2026-11-05',
    reason:
      'Stack-exhaustion DoS on deeply nested glob patterns. No fixed release exists (3.0.3 is latest). '
      + 'Reached only through nitropack > globby > fast-glob > micromatch, which expands build '
      + 'patterns from repository config, never request input.',
  },
];

const BLOCKING = new Set(['high', 'critical']);

export function advisoryId(advisory) {
  return advisory.url?.match(/GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}/)?.[0] ?? String(advisory.source);
}

// Returns blocking advisories, those excused by a live exception, and stale exceptions.
export function evaluateAudit(report, exceptions = EXCEPTIONS, today = new Date().toISOString().slice(0, 10)) {
  const advisories = new Map();
  for (const vulnerability of Object.values(report.vulnerabilities ?? {})) {
    for (const via of vulnerability.via) {
      if (typeof via !== 'object' || !BLOCKING.has(via.severity)) continue;
      advisories.set(advisoryId(via), { ...via, package: via.name ?? vulnerability.name });
    }
  }

  const live = new Map(exceptions.filter((e) => e.expires >= today).map((e) => [e.id, e]));
  const blocking = [];
  const excused = [];
  for (const [id, advisory] of advisories) {
    (live.has(id) ? excused : blocking).push({ id, ...advisory });
  }
  const stale = exceptions.filter((e) => !advisories.has(e.id));
  return { blocking, excused, stale };
}

function runAudit() {
  try {
    return execFileSync('npm', ['audit', '--package-lock-only', '--json'], { encoding: 'utf8' });
  } catch (error) {
    // npm audit exits non-zero when it finds anything; the JSON report is still on stdout.
    if (error.stdout) return error.stdout;
    throw error;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const { blocking, excused, stale } = evaluateAudit(JSON.parse(runAudit()));
  for (const a of excused) {
    const exception = EXCEPTIONS.find((e) => e.id === a.id);
    console.log(`excepted ${a.severity} ${a.package} ${a.id} until ${exception.expires}`);
  }
  for (const e of stale) {
    console.warn(`warning: exception ${e.id} (${e.package}) no longer matches an advisory; remove it`);
  }
  if (blocking.length) {
    for (const a of blocking) console.error(`${a.severity} ${a.package} ${a.id}: ${a.title} ${a.url ?? ''}`);
    console.error(`${blocking.length} blocking advisory(ies). Fix, or add a reviewed, dated exception.`);
    process.exit(1);
  }
  console.log('No blocking high or critical advisories.');
}
