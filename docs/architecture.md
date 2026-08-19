# Architecture

This project is a full-stack data product: scheduled ETL jobs transform public
source data, S3 stores immutable releases, FastAPI serves cacheable endpoints, and
the Nuxt frontend renders server content plus client-side maps and charts.

## Components

```text
packages/etl
  Extracts public source data, validates/transforms it, and writes processed outputs.

packages/dashboard-utils
  Shared S3 helpers, configuration, path conventions, and Pydantic models.

packages/api
  FastAPI service that loads processed/reference datasets from S3 and exposes
  dashboard-oriented endpoints.

packages/aws-batch-scraper
  Reusable ECS/SQS scraper framework for high-volume independent scrape tasks.

frontend
  Nuxt application with MapLibre maps, D3 charts, a civic UI layer, and Pinia state.
```

## Data Flow

```text
OpenDataPhilly / PPD / reference sources
  -> ETL extract modules
  -> transform and validation modules
  -> checksummed immutable S3 objects
  -> one atomic release pointer per core dataset
  -> FastAPI startup/lazy refresh snapshot
  -> versioned data endpoints + typed statistics JSON
  -> Nuxt SSR content and browser-side maps/charts on Cloudflare Workers
```

The courts pipeline has a separate batch path:

```text
incident IDs
  -> SQS queue
  -> ECS/Fargate scraper workers
  -> one S3 result JSON per incident
  -> aggregate/process workflow
  -> processed court-status dataset
```

## API Caching Strategy

The shootings API uses content-addressed URLs:

- `/shootings/meta` returns the current content version and available years.
- `/shootings/rows/{version}/{year}.ndjson` returns immutable year-specific rows.
- The frontend builds GeoJSON in the browser from NDJSON rows.

This avoids repeatedly transferring a single large GeoJSON file and lets browsers
cache stable year/version URLs aggressively.

Every handler captures one frozen application snapshot. A refresh is serialized,
fully reads, checksums, and validates a candidate off-state, then replaces one
pointer. Failed source checks keep serving the prior valid snapshot and remain
eligible for retry. The API retains the immediately previous shootings version so
clients holding an old manifest can complete an immutable year request during a
rollover.

The same shooting and homicide snapshot produces `/stats.json`. Nuxt uses it for
server-rendered statistics while owning the canonical HTML, robots, and sitemap.
Shooting and homicide freshness dates remain separate so each figure is labeled
accurately.

## Runtime Configuration

Python services use Pydantic settings and boto3's default credential chain.

- Local development should prefer `AWS_PROFILE`.
- GitHub Actions should use OIDC where possible.
- ECS workloads should use task roles.
- Static access keys are not passed into boto3 sessions by application code.

Infrastructure is provisioned outside this repository. The application-level
contracts are the S3 prefixes, ECS task/container names, SQS queue names, and
container commands documented in the package READMEs.

## Operational Workflow

- A continuously running, scheduler-only Fly app dispatches GitHub Actions ETL
  workflows. Scheduling remains outside GitHub so repository inactivity cannot
  disable refreshes. It holds only the fine-grained Actions token; the public
  API app holds only its read-only S3 credentials.
- The same external scheduler dispatches a daily production smoke workflow;
  failures make stale readiness, broken pages, or unavailable immutable
  downloads visible in GitHub Actions instead of relying on a liveness check.
- During the scheduler split-app rollout, the weekly frontend-quality check
  remains on its native GitHub schedule and is absent from the Fly crontab. Its
  ownership moves only in a separate quiet-window handoff after the isolated
  scheduler has demonstrated the expected cadence.
- ETL jobs upload complete immutable data/metadata objects and move a single
  stable pointer only after validation.
- The API refreshes its atomic S3-backed snapshot on startup and on a TTL; `/ready`
  reports missing or stale core data independently from `/health` liveness.
- Cloudflare Workers serves the Nuxt application at the canonical subpath.
- Fly.io serves the API.
- Courts scraping runs through ECS/SQS with validated queue envelopes and an S3
  run lease so individual failures are isolated and overlapping runs are refused.
