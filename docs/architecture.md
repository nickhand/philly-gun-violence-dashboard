# Architecture

This project is a full-stack data product: scheduled ETL jobs transform public
source data, S3 stores processed datasets, FastAPI serves cacheable endpoints, and
the Vue frontend renders maps and charts.

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
  Vue 3 application with MapLibre maps, D3 charts, Vuetify UI, and Pinia state.
```

## Data Flow

```text
OpenDataPhilly / PPD / reference sources
  -> ETL extract modules
  -> transform and validation modules
  -> S3 processed datasets + metadata
  -> FastAPI startup/lazy refresh cache
  -> versioned data endpoints + cached statistics HTML
  -> browser-side maps/charts or Netlify SEO-route proxy
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

The same loaded shooting and homicide datasets also produce `/stats` and
`/sitemap.xml`. Their rendered responses are cached by dataset version and ETag,
then re-rendered after startup or a lazy S3 refresh. Netlify proxies the canonical
`/philly-gun-violence-map/stats` and sitemap URLs to these endpoints. Shooting and
homicide freshness dates remain separate so each figure is labeled accurately.

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

- GitHub Actions run scheduled or manually triggered ETL jobs.
- ETL jobs write processed data and `meta.json` files to S3.
- The API refreshes its S3-backed caches on startup and on a TTL.
- Netlify deploys only for frontend/config changes and proxies dynamic SEO routes.
- Fly.io serves the API.
- Courts scraping runs through ECS/SQS so individual scrape failures are isolated.
