import assert from 'node:assert/strict';
import test from 'node:test';

import { EXCEPTIONS, evaluateAudit } from '../scripts/audit-dependencies.mjs';

const advisory = (name, severity, ghsa) => ({
  source: 1,
  name,
  severity,
  title: `${name} issue`,
  url: `https://github.com/advisories/${ghsa}`,
});

const report = (...vias) => ({
  vulnerabilities: Object.fromEntries(
    vias.map((via) => [via.name, { name: via.name, via: [via] }]).concat([
      // Transitive entries only point at other packages and must not count twice.
      ['parent', { name: 'parent', via: vias.map((via) => via.name) }],
    ]),
  ),
});

const exception = { id: 'GHSA-aaaa-bbbb-cccc', package: 'dep', expires: '2026-10-14', reason: 'test' };

test('blocks high and critical advisories without an exception', () => {
  const { blocking } = evaluateAudit(
    report(advisory('a', 'high', 'GHSA-1111-2222-3333'), advisory('b', 'critical', 'GHSA-4444-5555-6666')),
    [],
    '2026-10-06',
  );
  assert.deepEqual(blocking.map((a) => a.id), ['GHSA-1111-2222-3333', 'GHSA-4444-5555-6666']);
});

test('ignores moderate and low advisories', () => {
  const { blocking } = evaluateAudit(report(advisory('a', 'moderate', 'GHSA-1111-2222-3333')), [], '2026-10-06');
  assert.equal(blocking.length, 0);
});

test('excuses only the listed advisory while its exception is live', () => {
  const audit = report(advisory('dep', 'high', exception.id), advisory('other', 'high', 'GHSA-9999-8888-7777'));
  const { blocking, excused } = evaluateAudit(audit, [exception], '2026-10-14');
  assert.deepEqual(excused.map((a) => a.id), [exception.id]);
  assert.deepEqual(blocking.map((a) => a.id), ['GHSA-9999-8888-7777']);
});

test('an expired exception blocks again', () => {
  const { blocking } = evaluateAudit(report(advisory('dep', 'high', exception.id)), [exception], '2026-10-15');
  assert.deepEqual(blocking.map((a) => a.id), [exception.id]);
});

test('reports exceptions that no longer match any advisory', () => {
  const { stale } = evaluateAudit(report(), [exception], '2026-10-06');
  assert.deepEqual(stale.map((e) => e.id), [exception.id]);
});

test('every reviewed exception has a reason and a bounded expiry', () => {
  for (const e of EXCEPTIONS) {
    assert.match(e.id, /^GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}$/);
    assert.ok(e.reason.length > 40, `${e.id} needs a real reason`);
    assert.match(e.reviewed, /^\d{4}-\d{2}-\d{2}$/);
    assert.match(e.expires, /^\d{4}-\d{2}-\d{2}$/);
    const days = (Date.parse(e.expires) - Date.parse(e.reviewed)) / 86_400_000;
    assert.ok(days > 0 && days <= 60, `${e.id} expiry must be within 60 days of review`);
  }
});
