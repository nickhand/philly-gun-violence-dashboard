# Temporary node-forge security backport

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
