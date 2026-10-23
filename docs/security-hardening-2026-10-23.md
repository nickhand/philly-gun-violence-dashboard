# October 23, 2026 security and Actions review

## Applicability

The repository serves a Python FastAPI API and a Nuxt/Cloudflare frontend, with
Python ETL and Playwright/Chrome scraping. No PHP source, Composer manifest, PHP
server configuration, or PHP runtime installation was found in its application
or Docker definitions. The PHP2Shell vulnerabilities therefore have no identified
execution path here. This conclusion does not cover unrelated services or other
projects. The [PHP project advisory](https://www.php.net/archive/2026.php#2026-10-21-5)
covers CVE-2026-109618 and CVE-2026-109619 and the patched PHP releases; the same
page also records the October 23 session-upload follow-up.

The eMudhra incident **does affect the project's TLS clients and build tools**.
The [Python security announcement](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576)
requires separate updates to certifi, pip, and uv. Updating the operating system
alone does not replace pip's embedded certificate bundle. Existing images and
processes retain their old bundles until rebuilt and replaced.

## Changes

- Require uv **0.13.5** in repository configuration, every workflow, and every
  production/example Dockerfile. The
  [uv advisory](https://github.com/astral-sh/uv/security/advisories/GHSA-hq85-5cpj-mr62)
  fixes bundled trust in 0.13.4; the
  [0.13.5 release](https://github.com/astral-sh/uv/releases/tag/0.13.5) also refreshes
  managed Python downloads and their ensurepip bundles.
- Install pip **26.2.2** through the patched uv in each Python CI job, using the
  setup-python interpreter explicitly. The bootstrap ignores project resolver
  settings and waives an inherited freshness delay only for this exact tool version. Audit-tool environments also require
  patched pip and certifi, so a reused tool cache cannot retain an older bundle.
- Require certifi **2026.10.23** in all four independent Python locks. The original
  incident fix was 2026.10.19; the
  [October 23 bundle](https://github.com/certifi/python-certifi/compare/2026.10.19...2026.10.23)
  also removes the emSign C1 and C3 roots. Keep the normal one-week freshness
  policy, with explicit package exceptions for certifi, Playwright, and the
  separately fixed OpenTelemetry API **1.45.1**. CI checks that all four certifi locks agree.
- Update the API/scheduler base to Python **3.14.9**, and example bases to
  **3.13.17**, using verified image digests. Build assertions require patched pip
  and ensurepip. The Ubuntu scraper uses uv and does not install pip.
- Explicitly distrust the compromised emSign G3 root and the Comodo AAA
  cross-signing path in the container system trust stores. Image smoke checks
  inspect fingerprints in the actual loaded system and certifi bundles, following the
  [incident remediation guidance](https://emudhra.we-have-a-problem.com/#workarounds).
  The scraper retains its reviewed Ubuntu snapshot; trust removal happens before
  apt downloads and applies to both build and runtime stages.
- Update frontend CI Node to **22.23.4** and Playwright's embedded Node to
  **24.22.1**, including the image's SBOM contract. See the
  [Node security release](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases).
  Upgrade Python [Playwright to **1.64.1**](https://github.com/microsoft/playwright-python/releases/tag/v1.64.1),
  whose official wheel includes that patched Node. This also covers local runs
  and the daily homicide workflow. The running driver version is asserted during
  the build and image scan.
- Update the digest-pinned Grype scanner to **0.121.0**, which fixes five
  `golang.org/x/net` advisories including critical
  [GO-2026-6612](https://github.com/anchore/grype/releases/tag/v0.121.0), while
  retaining database schema 6 and every release gate. Its official image still
  reports Go **1.26.8**, so the version update alone does not fix eMudhra trust.
  The only networked scanner step, database download, now mounts the locked
  certifi bundle read-only and sets both `SSL_CERT_FILE` and `SSL_CERT_DIR` to
  prevent loading the image's older roots. The reviewed Syft **1.50.0** pin and
  schema **16.1.10** remain; Syft and vulnerability matching run with networking
  disabled and no Docker socket or registry credentials.
- Update DOMPurify to **3.4.17**, Nuxt to **4.6.2**, and Vitest/coverage to **4.1.12**;
  align Vue and Vue Router with Nuxt's runtime requirements. Reject unavailable or
  malformed npm audit responses instead of treating missing results as clean.
  Retain the existing audit thresholds and bundle limits.
- Update setup-uv to **10.3.2**, setup-python and setup-node to **7.1.0**,
  upload-artifact to **7.0.2**, download-artifact to **8.0.2**, and install-action to
  **2.87.30**, each pinned to its verified upstream commit. Already-current
  checkout, AWS credentials, and Dependabot metadata actions retain their pins.
  JavaScript Action runtimes themselves are supplied by GitHub's hosted runner;
  setup-node only selects the Node version used by project commands.

## Failing Actions

- [Chrome stable update](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/39923556905):
  the signed Chrome 156 executable is 300,920,136 bytes, exceeding the old
  300,000,000-byte cap. The resolver now hashes in 1 MiB chunks with a bounded
  500,000,000-byte cap. Package signatures and checksums remain mandatory.
- [Chrome deployment](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/39923598291):
  the current main commit lacked an ETL run after a token-originated Dependabot
  merge. Reconciliation now requests missing exact-main validation, defers
  running/failed checks, and requests deployment only after success. The release
  gate continues to reject stale commits and PR-only evidence.
- [Dependency security](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/39916742522):
  vulnerable certificate bundles and frontend dependencies required updates.
- [Dependabot Actions configuration](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/39270614653):
  a test required the previous download-artifact commit literally. It now requires
  exactly one immutable 40-character commit pin, allowing reviewed version updates.
- [Dependabot frontend](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/39261857053):
  that separate update branch exceeded the deferred-analytics budget. The targeted
  security update passes the existing budget; no budget increase was needed.

- [Dependabot Python](https://github.com/nickhand/philly-gun-violence-dashboard/pull/93):
  the newer type checker requires an async-generator return annotation on the
  API lifespan; newer Ruff requires UTC aliases and flags the public string enum.
  Correct the annotation and UTC aliases while preserving enum string behavior.
  Both current tools and the exact proposed Ruff/ty versions pass these checks.
  Existing bot PRs must rebase and rerun before their full graphs can be approved.

## Activation and verification

Source changes do not patch running infrastructure. After required PR checks pass,
rebuild images from the reviewed branch with layer caching disabled, and deploy the
API, scheduler, and scraper through their existing release gates. Replace existing
running tasks/processes, then verify health, freshness, image digests, SBOM evidence,
and runtime certificate/tool versions. The frontend must also complete its normal
artifact validation and deployment flow.

The image audit also identified Chrome 155 vulnerabilities fixed in
**156.0.8078.47**. This repair includes that signed, checksum-verified milestone
update and regenerates all lock consumers. Future automatic milestone updates
continue to require review. No deployment check, vulnerability severity threshold,
or certificate verification was disabled.

Run `uv sync --locked` in an existing ETL environment after updating the checkout
to replace the Playwright wheel and its embedded Node runtime.

## Machine-wide maintenance

Updated the active tools through their existing managers:

- uv was already 0.13.5.
- Homebrew Python 3.14.9 with pip/ensurepip 26.2.2, CA certificates 2026-10-20,
  and the required OpenSSL updates.
- uv-managed active Python 3.13.17 and 3.12.15, both with fixed ensurepip.
- mise Node 24.22.1. Existing terminals/app processes may retain their inherited
  PATH; open a fresh login shell (`exec zsh -l`) or use `mise exec node@24.22.1 -- ...`.
  Commands in an already-running Codex task may need `zsh -lc 'command'`.

Homebrew's Python 3.14 formula became versioned. Its documented `libexec/bin`
path was added to the login-shell configuration to preserve `python3`/`pip3` on
3.14 rather than falling back to Apple's Python. Older interpreter installations
were retained for other projects that pin them; those environments were not
blanket-rewritten. The uv Python stdlib initially loaded Apple's older `/private/etc/ssl/cert.pem`.
A guarded login-shell `SSL_CERT_FILE` default now selects Homebrew's maintained
`/opt/homebrew/etc/ca-certificates/cert.pem`, preserving existing overrides.
Fresh-login checks confirm G3/AAA absence across the active Python installations
and repository environments. Native macOS verifier policy and unrelated apps
were not independently verified or changed; Apple-managed files were untouched.
