import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const require = createRequire(import.meta.url);
const braces = require('braces');

// Keep hostile inputs isolated: a regression must fail, not exhaust the test runner's stack.
function bounded(source) {
  const result = spawnSync(
    process.execPath,
    [
      '--stack-size=512',
      '--max-old-space-size=64',
      '--input-type=module',
      '--eval',
      `import assert from 'node:assert/strict';
       import { createRequire } from 'node:module';
       const require = createRequire(${JSON.stringify(import.meta.url)});
       const braces = require('braces');
       const guarded = error => error instanceof Error
         && /exceeds max depth|parent chain contains a cycle/.test(error.message)
         && !/Maximum call stack/i.test(error.message);
       const nested = depth => '{'.repeat(depth) + 'a,b' + '}'.repeat(depth);
       const apis = ['parse', 'compile', 'expand', 'stringify'];
       ${source}`,
    ],
    { encoding: 'utf8', timeout: 5000, maxBuffer: 64 * 1024 },
  );
  assert.equal(result.error, undefined, result.error?.message);
  assert.equal(result.signal, null, result.stderr);
  assert.equal(result.status, 0, result.stderr || result.stdout);
}

test('deep braces, parentheses and mixed nesting fail with the intended guard in every public API', () => {
  bounded(`
    const patterns = [
      nested(3000),
      '('.repeat(3000) + 'x' + ')'.repeat(3000),
      '({'.repeat(1500) + 'a,b' + '})'.repeat(1500),
    ];
    for (const pattern of patterns) {
      for (const api of apis) assert.throws(() => braces[api](pattern), guarded, api);
    }
  `);
});

test('the mandatory depth limit accepts 100 levels and rejects 101', () => {
  bounded(`
    for (const api of apis) {
      for (const [open, close] of [['{', '}'], ['(', ')']]) {
        assert.doesNotThrow(() => braces[api](open.repeat(100) + 'a,b' + close.repeat(100)));
        assert.throws(() => braces[api](open.repeat(101) + 'a,b' + close.repeat(101)), guarded);
      }
    }
  `);
});

test('maxDepth can lower the limit but fractions and invalid or excessive values cannot bypass it', () => {
  bounded(`
    for (const api of apis) {
      for (const maxDepth of [1, 1.5]) {
        assert.doesNotThrow(() => braces[api](nested(1), { maxDepth }));
        assert.throws(() => braces[api](nested(2), { maxDepth }), guarded);
      }
      assert.doesNotThrow(() => braces[api](nested(2), { maxDepth: 2 }));
      for (const maxDepth of [0, -1, 0.5]) {
        assert.throws(() => braces[api](nested(1), { maxDepth }), guarded);
      }
      for (const maxDepth of [NaN, Infinity, -Infinity, 101, 1e9, Number.MAX_VALUE,
        'unlimited', '10000', null, false, {}]) {
        assert.throws(() => braces[api](nested(101), { maxDepth }), guarded);
      }
    }
  `);
});

test('direct AST callers cannot bypass child depth or cycle guards', () => {
  bounded(`
    function ast(depth) {
      const root = { type: 'root', nodes: [] };
      let node = root;
      for (let i = 0; i < depth; i++) {
        const child = { type: 'paren', nodes: [], parent: node };
        node.nodes.push(child);
        node = child;
      }
      node.nodes.push({ type: 'text', value: 'x' });
      return root;
    }
    for (const api of ['compile', 'expand', 'stringify']) {
      assert.doesNotThrow(() => braces[api](ast(100)));
      assert.throws(() => braces[api](ast(101)), guarded);
      assert.throws(() => braces[api](ast(101), { maxDepth: Infinity }), guarded);
      assert.throws(() => braces[api](ast(2), { maxDepth: 1.5 }), guarded);
      const cycle = { type: 'root', nodes: [] };
      cycle.nodes.push(cycle);
      assert.throws(() => braces[api](cycle), guarded);
    }
  `);
});

test('expand bounds cyclic and acyclic parent chains on caller-provided ASTs', () => {
  bounded(`
    const self = { type: 'paren', nodes: [{ type: 'text', value: 'x' }] };
    self.parent = self;
    assert.throws(() => braces.expand(self), guarded);
    const first = { type: 'paren', nodes: [{ type: 'text', value: 'x' }] };
    const second = { type: 'paren', parent: first };
    first.parent = second;
    assert.throws(() => braces.expand(first), guarded);
    function parentChain(depth) {
      let parent = { type: 'root', queue: [] };
      for (let i = 1; i < depth; i++) parent = { type: 'paren', parent };
      return { type: 'paren', parent, nodes: [{ type: 'text', value: 'x' }] };
    }
    const parentGuarded = error => guarded(error) && /AST parent depth/.test(error.message);
    for (const maxDepth of [undefined, Infinity, 1000000]) {
      assert.deepEqual(braces.expand(parentChain(100), { maxDepth }), ['x']);
      assert.throws(() => braces.expand(parentChain(101), { maxDepth }), parentGuarded);
    }
    for (const maxDepth of [1, 1.5]) {
      assert.deepEqual(braces.expand(parentChain(1), { maxDepth }), ['x']);
      assert.throws(() => braces.expand(parentChain(2), { maxDepth }), parentGuarded);
    }
    assert.deepEqual(braces.expand(parentChain(2), { maxDepth: 2 }), ['x']);
  `);
});

test('ordinary globs, ranges, quoted text and escaped literals retain their results', () => {
  const cases = [
    ['src/{api,utils}/*.{js,ts}', ['src/api/*.js', 'src/api/*.ts', 'src/utils/*.js', 'src/utils/*.ts']],
    ['{a,{b,c}}', ['a', 'b', 'c']],
    ['{03..01}', ['03', '02', '01']],
    ['{,a}/x', ['/x', 'a/x']],
    [String.raw`src/\{literal\}/{a,b}`, ['src/{literal}/a', 'src/{literal}/b']],
    ['"{{literal}}"/{a,b}', ['{{literal}}/a', '{{literal}}/b']],
    ['[{a,b}]/{x,y}', ['[{a,b}]/x', '[{a,b}]/y']],
    ['${a,b}/{c,d}', ['${a,b}/c', '${a,b}/d']],
  ];
  for (const [pattern, expected] of cases) assert.deepEqual(braces.expand(pattern), expected);
  assert.deepEqual(braces.expand('{,a,a}', { nodupes: true, noempty: true }), ['a']);
  assert.throws(() => braces.expand('{1..1001}'), /range limit/i);
  const range = new RegExp(`^${braces.compile('file-{01..03}.txt')}$`);
  for (const filename of ['file-01.txt', 'file-02.txt', 'file-03.txt']) assert.ok(range.test(filename));
  for (const filename of ['file-00.txt', 'file-04.txt', 'file-1.txt']) assert.equal(range.test(filename), false);
  for (const pattern of ['{{a}}', '{a,{b}}', '{{x}y}', '{a,{b,{c}}}', '{}{a}']) {
    assert.equal(braces.stringify(braces.parse(pattern), { escapeInvalid: true }), pattern);
  }
  // Literal delimiters are not nesting, even when there are more than 100 of them.
  const literal = '{'.repeat(150) + 'x' + '}'.repeat(150);
  assert.deepEqual(braces.expand(`"${literal}"`), [literal]);
  assert.deepEqual(braces.expand(`[${literal}]`), [`[${literal}]`]);
  assert.deepEqual(braces.expand(String.raw`\{`.repeat(150)), ['{'.repeat(150)]);
});

test('micromatch, fast-glob and globby preserve real file matching and reject excessive nesting', async () => {
  const micromatch = require('micromatch');
  const fastGlob = require('fast-glob');
  const { globby } = await import('globby');
  assert.deepEqual(micromatch.braceExpand('src/{api,utils}/*.ts'), ['src/api/*.ts', 'src/utils/*.ts']);
  const cwd = mkdtempSync(join(tmpdir(), 'braces-security-'));
  try {
    for (const directory of ['src/api', 'src/utils', 'other']) mkdirSync(join(cwd, directory), { recursive: true });
    for (const file of ['src/api/a.ts', 'src/api/b.js', 'src/utils/c.ts', 'other/ignored.ts']) {
      writeFileSync(join(cwd, file), '');
    }
    const pattern = 'src/{api,utils}/*.{js,ts}';
    assert.deepEqual(fastGlob.sync(pattern, { cwd }).sort(), ['src/api/a.ts', 'src/api/b.js', 'src/utils/c.ts']);
    assert.deepEqual((await globby(pattern, { cwd, ignore: ['**/*.js'] })).sort(), ['src/api/a.ts', 'src/utils/c.ts']);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
  bounded(`
    const micromatch = require('micromatch');
    const fastGlob = require('fast-glob');
    const { globby } = await import(require.resolve('globby'));
    const pattern = nested(3000);
    assert.throws(() => micromatch.parse(pattern), guarded);
    assert.throws(() => micromatch.braceExpand(pattern), guarded);
    assert.throws(() => fastGlob.generateTasks(pattern), guarded);
    await assert.rejects(async () => globby(pattern), guarded);
  `);
});

test('the installed dependency and sole locked copy use the reviewed local archive', () => {
  assert.equal(require('braces/package.json').version, '3.0.4-philly.1');
  const micromatchRequire = createRequire(require.resolve('micromatch'));
  assert.equal(micromatchRequire.resolve('braces'), require.resolve('braces'));
  const archive = readFileSync(new URL('../vendor/braces-3.0.4-philly.1.tgz', import.meta.url));
  assert.equal(
    createHash('sha256').update(archive).digest('hex'),
    '915f19c374268cfb3f1575850d231119586670e276fdc5f73475ffaa8d9808a4',
  );
  const lock = JSON.parse(readFileSync(new URL('../package-lock.json', import.meta.url), 'utf8'));
  const copies = Object.entries(lock.packages).filter(([path]) => path.endsWith('/braces'));
  assert.equal(copies.length, 1);
  assert.equal(copies[0][1].version, '3.0.4-philly.1');
  assert.equal(copies[0][1].resolved, 'file:vendor/braces-3.0.4-philly.1.tgz');
});
