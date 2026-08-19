# API

FastAPI service for the Philadelphia Gun Violence Dashboard. Provides versioned, year-specific data endpoints backed by S3.

## Key Endpoints

### Shootings
- `GET /shootings/meta` — Primary entry point returning version, available years, and per-year URLs
- `GET /shootings/rows/{version}/{year}.ndjson` — Year-specific NDJSON data (immutable, aggressively cached)

### Boundaries
- `GET /boundaries` — List available boundary datasets
- `GET /boundaries/{dataset}` — GeoJSON for a specific boundary dataset

### Streets
- `GET /streets?segment_ids=...&limit=2000&offset=0` — Street block GeoJSON (paginated)

### Homicides
- `GET /homicides/{year}` — Annual and YTD homicide totals

### Meta (Data Freshness)
- `GET /meta` — Last updated timestamps for all datasets
- `GET /meta/shootings`, `GET /meta/homicides`, `GET /meta/courts`

### Crawler-visible statistics
- `GET /stats` — Current server-rendered statistics, year table, and FAQ HTML
- `GET /stats.json` — The same statistics snapshot as typed JSON for SSR clients
- `GET /sitemap.xml` — Sitemap with modification dates from the loaded datasets

### Health
- `GET /health` — Process liveness used by Fly; never calls S3
- `GET /ready` — Loaded snapshot freshness; returns 503 for missing or stale core data

## Caching Strategy

The API uses a versioned, content-addressed caching strategy:

1. **Meta endpoint** (`/shootings/meta`) returns a content-based version hash and ETag
2. **Year-specific endpoints** include the version in the URL path, making them immutable
3. Frontend caches versioned URLs for 1 year (`Cache-Control: public, max-age=31536000, immutable`)

The statistics JSON, HTML, and sitemap share one snapshot rendered after
startup. They are invalidated when either the shooting or homicide cache
refreshes, use ETags for revalidation, and preserve the distinct freshness date
for each dataset.

All request handlers capture one frozen application snapshot. Refreshes are
serialized, build and validate a complete candidate off-state, and swap one
pointer only after success. Transient S3 failures keep serving the last valid
snapshot and remain eligible for the next retry. The shootings snapshot retains
only its immediately previous content version so a client that fetched the old
manifest during rollover can still finish its immutable year request. The
shared S3 manifest names that N-1 release too, so the guarantee survives an API
restart.

## Environment

Required configuration:
- `AWS_REGION`
- `S3_BUCKET` or `AWS_BUCKET_NAME`
- `S3_PROCESSED_PREFIX` (default: `processed`)

AWS credentials are resolved through boto3's default credential chain. Use
`AWS_PROFILE` locally; use runtime secrets, OIDC, or instance/task roles in
deployed environments. In addition to its existing processed/reference reads,
the API runtime identity must have `s3:GetObject` for
`public/downloads/manifest.json`; startup fails closed if that common shootings
pointer cannot be read.

Boundary endpoints similarly follow
`reference/boundaries_release.json` to one content-addressed generation under
`reference/boundaries/releases/`. The API validates the manifest version, every
exact configured key, and each SHA-256 checksum before atomically installing the
whole generation. During the reader-first rollout it falls back to the original
string-valued `reference/boundaries_manifest.json`; that compatibility pointer
also names immutable release members after the new publisher runs. Legacy
sources are never used after a release-backed snapshot has loaded.

The deployed identity is `fly-philly-gv-dashboard-api`. Grant that user only
`s3:GetObject` on
`arn:aws:s3:::philly-gun-violence-dashboard/public/downloads/manifest.json` in
addition to its existing processed/reference reads; no bucket listing, write,
ACL, or KMS permission is required.

Optional:
- `API_REFRESH_TTL_SECONDS` (default: 300) — How often to check S3 for data updates
- `API_REFRESH_FAILURE_BACKOFF_SECONDS` (default: 30) — Minimum delay before retrying a failed S3 refresh while the complete stale snapshot remains available
- `API_READINESS_MAX_DATA_AGE_DAYS` (default: 14) — Maximum core-data age for `/ready`

## Local Development

```bash
just api-dev
```

Audit every visible stats-page figure, table row, freshness date, JSON-LD answer,
and sitemap date against the API payloads:

```bash
uv run python scripts/audit_stats_consistency.py http://127.0.0.1:8000
```

## Deployment (Fly.io)

The first atomic-release deployment is reader-first. Before enabling any
scheduler that can dispatch the updated workflows, set the repository variable
`EXPECT_ATOMIC_RELEASE=false`, configure the independent smoke-test heartbeat,
and verify that `fly-philly-gv-dashboard-api` can read
`public/downloads/manifest.json`. The exact least-privilege IAM grant is
documented above. Keep the legacy API `GITHUB_PAT` temporarily: importing the
API's S3 secrets does not remove an existing Fly secret, and the token is needed
until schedule ownership has been proven on the isolated app.

```bash
just fly-secrets-api         # Give the API only its read-only S3 credentials
just fly-deploy-api          # Deploy the 1 GB pointer-aware reader first
# Verify /health, /ready, 1 GB RAM, and legacy-backed readiness here.
just fly-create-scheduler    # One-time app creation; skip if it already exists
just fly-secrets-scheduler   # Give the scheduler only its Actions token
just fly-stop-legacy-scheduler # Quiet-window handoff: remove the API cron owner
just fly-deploy-scheduler    # Enable current-main workflow dispatches
# Observe exactly one expected dispatch and require it to succeed here.
just fly-remove-legacy-api-token # Only now delete the API GITHUB_PAT
```

The API and scheduler are separate Fly apps so a compromise of the public API
cannot expose the GitHub Actions credential. The scheduler has no HTTP service
and receives no AWS credentials; the API receives no `GITHUB_PAT`.

Deploy `fly.toml` before the scheduler handoff and require the started `app`
Machine to have the configured 1 GB of memory. `/health` and `/ready` must pass,
and before the first pointer is published every dataset reported by `/ready`
must be current and have `source: "legacy"`. Do not manually run, or enable a
scheduler that can run, the updated shootings, homicide, or boundary writers
until this reader proof succeeds. A missing `/ready`, an unreadable shared
manifest, or a non-current legacy dataset stops the rollout.

Only after that reader gate succeeds, choose a quiet window away from every cron
minute. Verify that no scheduler-started GitHub workflow or courts ECS monitor
is still active. Then create/configure the isolated app, run
`just fly-stop-legacy-scheduler`, and only after that succeeds run
`just fly-deploy-scheduler`. The deploy recipe refuses to proceed while any
legacy API `cron` Machine exists, replaces scheduler Machines with Fly's
`immediate` strategy and HA disabled, scales the `cron` group to one, and checks
that exactly one Machine is started. This intentionally creates a short quiet
gap; never deploy the new scheduler before stopping the old cron owner. The
Machine guard cannot prove that an already-dispatched GitHub or ECS job is
finished, which is why the operator check is a required first step.

Treat the scheduler deployment as enabling the current `main` writers. Observe
exactly one expected natural dispatch, verify that it finishes successfully,
and inspect GitHub before any manual re-dispatch. Only after that proof may the
obsolete API token be removed with `just fly-remove-legacy-api-token`. Confirm
afterward that the scheduler app holds only `GITHUB_PAT` and the API app does not
hold it; this explicit removal is a required credential-isolation gate.

Workflow dispatch POSTs are non-idempotent. The scheduler retries only an
explicit HTTP 429, which proves GitHub did not accept the request. A timeout,
connection loss, server error, or undocumented success response exits with a
delivery-unknown error and is not retried. Inspect GitHub Actions before any
manual re-dispatch so a lost response cannot create a duplicate run.

The weekly frontend production check uses a separate two-phase handoff so this
release cannot disable it before the new scheduler is live. In phase 1,
`.github/workflows/frontend-quality.yml` retains its native Monday schedule and
the Fly crontab deliberately omits it. After the isolated scheduler has produced
the expected ETL and smoke runs, choose a quiet window just after the weekly
check: add
`30 9 * * 1 python scripts/dispatch_workflow.py frontend-quality.yml` to
`packages/api/crontab`, deploy and verify the single scheduler Machine, then
remove the native GitHub schedule in the same maintenance window. Do not leave
both owners enabled across a scheduled minute.

For the first atomic-release rollout, deploy this pointer-aware API before
running the updated shootings or homicides ETL. First verify the API runtime can
read `public/downloads/manifest.json`. Until a release pointer exists,
the API reads the legacy stable objects. After it has observed a valid pointer,
it never falls back to mutable compatibility mirrors if that pointer disappears
or becomes unreadable; it serves the prior in-memory release instead. This makes
the safe order: API deploy, health/readiness check, ETL deploy, one ETL run, then
verify `/meta`, `/shootings/meta`, `/ready`, and a current plus N-1 row URL.

The same reader-first gate applies independently to boundaries. Before the first
updated `etl-boundaries` run, verify the deployed API can read
`reference/boundaries_release.json` (a missing object is expected before first
publication), the legacy `reference/boundaries_manifest.json`, and immutable
members under `reference/boundaries/releases/`. Publish one generation, then
verify `/boundaries` and every listed member before considering the boundary
writer migrated. The legacy manifest remains in its original schema for old
instances and rollback builds.

The Fly Supercronic process also dispatches `production-smoke.yml` daily after
the data jobs. That externally triggered workflow checks API liveness and
freshness, indexable public pages, the manifest contract, and every immutable
download URL. Its schedule remains outside GitHub so the same inactivity rule
cannot silently disable monitoring.

Configure an independent dead-man check before enabling that schedule. Store
its success-ping URL as the GitHub Actions secret
`PRODUCTION_SMOKE_HEARTBEAT_URL` and set the service to alert when the daily ping
is missed. Because the workflow pings only after every contract check succeeds,
the monitor also detects a stopped scheduler, an expired/under-scoped PAT, a
disabled workflow, or a failing production smoke. Rotate the scheduler's
fine-grained Actions token before its expiry and verify the expected GitHub run
cadence during that rotation.

Set the repository variable `EXPECT_ATOMIC_RELEASE=false` explicitly during the
first reader-first API deployment. After the shootings, homicide, and boundary
pointers are live, set it to `true`; subsequent smoke runs then require
release-backed readiness and the manifest's application-data contract rather
than accepting legacy compatibility sources. An absent variable defaults to
`true`, so configuration drift cannot silently weaken the production check.
