# Temporary security backports

## node-forge: CVE-2026-85393

`listhen` uses node-forge to generate development HTTPS certificates. On October 2,
2026, the latest published node-forge (1.4.0) still accepts extra children inside
RSA DigestAlgorithm structures: [CVE-2026-85393](https://github.com/advisories/GHSA-86w9-cpqp-85rv).

The local package `1.4.1-philly.1` is **our backport, not an upstream release**.
It starts from the [published 1.4.0 tarball](https://registry.npmjs.org/node-forge/-/node-forge-1.4.0.tgz)
with registry SHA-512:

```
LarFH0+6VfriEhqMMcLX2F7SwSXeWwnEAJEsYm5QKWchiVYVvJyV9v7UDvUv+w5HO23ZpQTXDv/GxdDdMyOuoQ==
```

The only library change is the checked-in patch from [upstream PR #1152](https://github.com/digitalbazaar/forge/pull/1152),
commit `ceba34402e329f0365134f23fe19898756527d65`. It validates nested element
counts in addition to the existing outer DigestInfo checks. The package retains
all upstream Node library files and the original license. Unpatched browser
bundles, Flash assets, upstream development dependencies, and build scripts are
excluded. Package metadata explicitly identifies the backport and forbids publishing.

Rebuild deterministically from the authenticated original archive:

```sh
python3 frontend/vendor/build-node-forge-backport.py /path/to/node-forge-1.4.0.tgz
```

The output SHA-256 is `ea17a195ef66d4b10c9fb3093c26516d40be0da7d14b53ca6a842bc31e2b1ccc`;
npm also records its SHA-512 integrity in the lock. `npm run test:dependency-security`
tests the installed package with malformed nested/outer ASN.1 structures, valid
signatures with and without NULL parameters, Node RSA interoperability, and
development certificate generation. The nested regression was reproduced against
unmodified 1.4.0, which incorrectly returned true. CI runs these tests before the
unchanged vulnerability audit.

Remove the local archive, override, and rebuild helper when a published upstream
fix passes these regression tests and the audit. Retain the behavioral tests.
Do not replace this with an advisory ignore or an unmodified package version bump.


## braces: CVE-2026-93687

As of October 13, 2026, the latest official `braces` release is 3.0.3 and
[GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) has no
published fixed version. Deeply nested brace or parenthesis patterns can exhaust
recursive walkers even below the existing 10,000-character input limit. The
previous audit exception expires on November 5, 2026.

Our dependency path is Nuxt → `@nuxt/nitro-server` → Nitro → `globby` →
`micromatch` (directly and through `fast-glob`) → `braces`. Current Nitro uses
these globs for build discovery; the deployed Cloudflare artifact does not include
this chain. Updating the supported parent releases does not remove `braces`.
A replacement glob library would require changes to Nitro's imports and behavior.

`3.0.4-philly.1` is **our private backport, not an upstream release**. It starts
from the [published 3.0.3 tarball](https://registry.npmjs.org/braces/-/braces-3.0.3.tgz)
with registry SHA-512:

```
yQbXgO/OSZVD2IsiLlro+7Hf6Q18EJrKSEsdoMzKePKXct3gvD8oLcOQdIzGupr5Fj+EDe8gO/lxc1BzfMpxvA==
```

The checked-in patch applies only the five library-file changes from
[upstream PR #87](https://github.com/micromatch/braces/pull/87), exact head
`d44b9b1ee12e7804d4232d5a47a4a0c61d2fbefe`, onto the published package. That PR is
unmerged. Its base includes unrelated changes after 3.0.3; those changes are not
included here. We additionally bound the expansion queue's acyclic parent walk,
using the same depth limit. This closes the gap left by cycle detection alone;
see the equivalent [downstream parent-chain correction](https://github.com/awslabs/cli-agent-orchestrator/blob/main/patches/%40dieub%2Bbraces-depth-guard%2B3.0.3-pn.3.patch).

The patch caps brace/parenthesis parsing and AST container traversal at 100 nested
levels. A caller may lower `maxDepth`, but cannot raise the cap or bypass it with
non-finite values. Expansion also bounds parent traversal and rejects parent
cycles. Escaped, quoted, and bracket-literal delimiters retain their existing
semantics. Inputs above the cap intentionally fail with a descriptive error.
This mitigates excessive nesting; it does not promise to bound expansion
cardinality, AST width, or every arbitrary malformed JavaScript object. Existing
range-expansion limits remain unchanged.

The archive retains all runtime source files and the MIT license, removes
upstream development dependencies and scripts, and sets `private: true`.
The direct file dependency plus `$braces` override ensures every transitive
consumer resolves this one archive. No registry version or moving Git branch is
substituted silently.

Rebuild deterministically from the authenticated original archive:

```sh
python3 frontend/vendor/build-braces-backport.py /path/to/braces-3.0.3.tgz
```

The output SHA-256 is
`915f19c374268cfb3f1575850d231119586670e276fdc5f73475ffaa8d9808a4`.
The helper verifies both the original archive and the output; npm also records
the output's SHA-512 integrity in the lockfile. `npm run test:dependency-security`
checks the installed backport's behavior, archive integrity, single locked copy,
and real `micromatch`/`fast-glob`/`globby` integration. Dangerous inputs run in
bounded subprocesses, and assertions distinguish intended depth errors from a
stack overflow or hang. npm audit alone cannot verify a custom patch; these
behavioral and integrity checks are required evidence for removing the exception.

Replace this archive and override with an official fixed release when one exists
and passes the regression and frontend quality checks. Retain the behavioral
security tests and update only their provenance assertions. Do not extend the
exception, dismiss the advisory, or use a version-only change as a substitute
for the actual fix.
