# Dependency backlog cleanup: 2026-09-22

The routine Python batch (#42) and frontend batch (#39) initially failed CI.
The replacement also includes the verified Actions batch (#48): setup-uv 8.3.2,
configure-aws-credentials 6.3.0, and install-action 2.87.13, all pinned by SHA.
They need these compatibility changes together with their dependency updates:

- Declare Click as a scraper test dependency. Typer's updated dependency tree no
  longer supplies the `click.utils.strip_ansi` import used by the CLI tests.
- Use `StrEnum` for court classifications and retain a validated coordinate
  system across spatial joins, satisfying the updated Ruff and ty checks.
- Refresh the API and ETL lockfiles after updating local package requirements.
  Clean image builds enforce those relationships with `uv sync --locked`.
- Install browser binaries through the locked Playwright package, as in
  [Playwright's CI setup](https://playwright.dev/docs/ci-intro). This removes the
  second, independently maintained browser-image version. Chromium, Firefox,
  WebKit, the legacy and Nuxt suites, and Lighthouse remain required.

Local validation: 1,053 Python tests across all four packages; package lock,
format, lint, and type checks; frontend type checks and unit coverage; 61 CI
contract tests; and pinned actionlint. Complete GitHub CI must also pass before
this replacement can supersede the original PRs. No production deployment is
implied by merging the dependency updates.

The automation bootstrap also encountered a PyPI audit timeout and a temporary
HTTP 503 from Canonical's snapshot service. Once the snapshot recovered, its
OpenSSL download matched the original pinned SHA-256. No checksum or security
check was bypassed.

Python audits now allow 60 seconds per upstream request after the observed
15-second PyPI timeout. Strict vulnerability checks remain enabled.
