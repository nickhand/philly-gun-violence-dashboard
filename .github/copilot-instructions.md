# Philadelphia Gun Violence Dashboard — contributor instructions

## Architecture

This monorepo is a typed data platform with four Python packages and one frontend:

- `packages/etl`: validates public source data and publishes immutable S3 releases.
- `packages/api`: FastAPI service that validates a complete release, builds indexes off-state,
  and atomically swaps one frozen in-memory snapshot.
- `packages/dashboard-utils`: shared Pydantic models, paths, and storage utilities.
- `packages/aws-batch-scraper`: reusable SQS/ECS court-scraper orchestration.
- `frontend`: canonical Nuxt 4 / Vue 3 / MapLibre / D3 dashboard deployed to Cloudflare
  Workers. The Vite SPA is retained only as a temporary rollback artifact.

Production data flow is:

```text
public sources -> ETL validation -> immutable S3 objects -> atomic release pointer
  -> validated API snapshot -> versioned NDJSON and stats -> Nuxt dashboard
```

The Fly scheduler is the long-term owner of GitHub `workflow_dispatch` cadence because
GitHub may disable scheduled workflows after repository inactivity. During the guarded
split-app cutover, `frontend-quality.yml` deliberately keeps its native weekly schedule and
is absent from the Fly crontab; transfer that final schedule only through the documented
phase-2 quiet-window handoff. Do not move ETL, production-smoke, or dependency-security
cadence back to GitHub.

## Python tooling

- Python is 3.13+ and dependencies are locked independently in each package with `uv`.
- The repository requires exact `uv 0.12.0`; use `uv run`, `uv add`, `uv lock`, and
  `uv sync`, never bare `pip` or Poetry.
- Use Ruff for linting and formatting and `ty` for strict type checking. Do not add mypy.
- Prefer root `just` recipes when one exists. Run `just --list` to discover current names.
- Do not run package entry points with bare `python`; run them through `uv run` or `just`.

Before handing off Python changes, run the affected package's lock check, Ruff format check,
Ruff lint, `ty check`, and pytest suite. Tests are first-class production code and are included
in formatting and lint gates.

## Robust Python expectations

- Make illegal states unrepresentable with precise types, frozen models/dataclasses, enums,
  and explicit `None`/Unknown states. Never coerce missing evidence to `False`.
- Validate untrusted data at every boundary: HTTP, HTML/DOM, S3 JSON, CSV/GeoJSON, SQS, ECS,
  environment variables, and CLI inputs. Return normalized validated values rather than the
  original untrusted object.
- Keep functions small and contracts explicit. Inject clients and clocks where doing so makes
  retry, failure, and concurrency behavior deterministic in tests.
- Catch only errors that can be handled meaningfully. Do not turn transport, authorization,
  malformed-data, or UI-drift failures into empty-success results.
- Preserve causality when raising domain errors and distinguish pre-commit failure from a
  release that committed but whose compatibility mirror failed.
- Build complete candidates away from shared state, validate them, then publish or swap one
  pointer atomically. Readers must capture one snapshot once per request.
- Treat retries and side effects as an idempotency problem. Ambiguous ECS/S3/HTTP outcomes fail
  closed; leases are released only with terminal evidence.
- Prefer immutable/content-addressed objects. Retain the current and previous distinct shooting
  content versions; never mutate bytes behind an immutable URL.
- Add regression tests for the failure mode, not merely the happy path. Include malformed input,
  partial failure, retry, concurrency, stale-state, and migration cases when relevant.

## Data contracts and publication

Shared public models live under `packages/dashboard-utils/src/dashboard_utils/models`. A field
change normally requires coordinated updates to the shared model, ETL transform/export, API
validation/router, Nuxt and legacy TypeScript contracts, user-facing methodology, and tests.

ETL publication order is strict:

1. validate the complete candidate;
2. upload every immutable release object;
3. atomically move the authoritative release pointer;
4. update non-authoritative compatibility mirrors.

The API prefers release pointers and supports legacy mirrors only for migration. Lazy refresh is
serialized, stale-on-error, and atomic; `/health` is process liveness while `/ready` verifies
release validity and freshness. Do not reintroduce independent mutable `app.state` dataset fields
or depend on an API restart for ordinary data adoption.

Court-search results are tri-state: `True` means an automated incident-number search returned a
result, `False` is trusted only when the portal displayed an explicit no-results marker under the
current semantics version, and `None` means unknown. A result does not establish identity,
relationship to a victim, or case outcome.

Only a forced, unsampled courts run may replace the stable flags and metadata. Run manifests
record explicit `sample`/`incremental`/`full` selection provenance and pre-selection candidate
counts. Shootings publication requires a complete full-run contract and a matching canonical
flags digest; never infer full coverage from a large row count. New shootings after that snapshot
remain unknown until the next full scrape.

Court workers use validated run-scoped SQS envelopes/results and an S3 lease. Production uses
distinct, exact `ECS_TASK_DEFINITION` (worker) and `ECS_MONITOR_TASK_DEFINITION` (monitor)
revisions backed by the exact verified `ECS_EXPECTED_IMAGE_URI`. Never use `latest`, a bare
family, an unverified digest, or a shared definition: semantic ECS preflight runs before
submission, and only the monitor definition may receive the GitHub dispatch token through its
ECS `secrets` list.

## Frontend

- Canonical app: Nuxt code in `frontend/app` and the reusable civic layer in
  `frontend/layers/civic-ui`.
- Rollback app: legacy Vite code in `frontend/src`; keep its contracts aligned while it remains
  a supported rollback path.
- Package manager: the exact npm version in `frontend/package.json`.
- Main checks: `npm run type-check`, `npm run type-check:nuxt`, `npm run test:coverage`,
  `npm run test:nuxt:seo`, the Playwright project matrix, both builds, bundle policy,
  Lighthouse policy, Cloudflare artifact checks, and full plus production dependency audits.
- Preserve server-rendered links/content, mobile WebKit behavior, keyboard/touch accessibility,
  no-overflow layouts at narrow widths, print pagination, security headers, and noindex behavior
  in staging.

Production is the `philly-gun-violence-dashboard-production` Cloudflare Worker on the exact
`/philly-gun-violence-map` namespace. A push runs quality checks; it does not authorize or perform
the explicit production deploy.

## Secrets, deploys, and operational safety

- Never print, commit, interpolate into echoed shell commands, or place secrets in process
  arguments. Use environment references and stdin-based secret import.
- Use least-privilege, workload-specific identities. The public API must not carry the scheduler
  GitHub token; the scheduler must not carry API S3 credentials.
- Do not change release pointers, DNS, IAM, Fly, Cloudflare, S3 lifecycle, queues, ECS task
  definitions, or production routes as part of a code review unless the task explicitly includes
  that external mutation and rollback is prepared.
- Treat Docker image builds, clean-checkout installs, production smoke checks, and IAM/lifecycle
  verification as release gates. Local unit success is not a substitute.
- Preserve unrelated work in a dirty tree. Stage explicit paths and inspect the staged snapshot,
  secret scan, and `git diff --cached --check` before committing.

Read `README.md`, `docs/architecture.md`, `packages/api/README.md`, and the package README closest
to the code before changing a cross-package or deployment contract.
