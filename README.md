<p align="center">
  <img width="560" src="./frontend/public/og-image.png" alt="Philadelphia Gun Violence Dashboard preview" />
</p>

# Philadelphia Gun Violence Dashboard

[![Daily Shootings ETL](https://github.com/nickhand/philly-gun-violence-dashboard/actions/workflows/daily-shootings-sync.yml/badge.svg)](https://github.com/nickhand/philly-gun-violence-dashboard/actions/workflows/daily-shootings-sync.yml)
[![Daily Homicide ETL](https://github.com/nickhand/philly-gun-violence-dashboard/actions/workflows/daily-homicide-sync.yml/badge.svg)](https://github.com/nickhand/philly-gun-violence-dashboard/actions/workflows/daily-homicide-sync.yml)
[![Courts Process](https://github.com/nickhand/philly-gun-violence-dashboard/actions/workflows/courts-process.yml/badge.svg)](https://github.com/nickhand/philly-gun-violence-dashboard/actions/workflows/courts-process.yml)

A full-stack data platform, API, and Vue dashboard for exploring public gun violence data in Philadelphia.
Visit the live map: https://nickhand.dev/philly-gun-violence-map

## What This Demonstrates

- Production-style geospatial data engineering: extract, validate, enrich, version, and serve public datasets.
- Typed Python package boundaries across ETL, shared utilities, scraper orchestration, and API code.
- A FastAPI backend designed around immutable, versioned NDJSON payloads for efficient frontend caching.
- A Vue 3/MapLibre/D3 frontend for map-first analysis with synchronized charts and filters.
- Operational automation with GitHub Actions, AWS S3, ECS/SQS scraper workers, Fly.io, and Netlify.

## System Overview

```text
public data sources
  -> Python ETL jobs
  -> S3 processed/reference datasets
  -> FastAPI cache + versioned endpoints
  -> Vue dashboard

Pennsylvania court portal
  -> SQS work queue
  -> ECS/Fargate scraper workers
  -> S3 per-incident results
  -> courts processing workflow
```

The API loads processed data from S3, builds in-memory indexes, and exposes
content-addressed URLs such as `/shootings/rows/{version}/{year}.ndjson`. The
frontend converts those rows to GeoJSON client-side, which keeps network payloads
small and cacheable while still supporting map interaction.

Infrastructure is provisioned outside this repository. The repo documents the
runtime contracts - environment variables, container commands, S3 keys, and ECS/SQS
expectations - without coupling the application to a specific IaC implementation.

## What This Repo Contains

- **Vue 3 dashboard** with interactive maps and data visualizations.
- **FastAPI service** for geospatial endpoints and dashboard data.
- **ETL pipelines** that ingest, clean, and enrich shootings, homicides, courts, and boundaries data.
- **Shared utilities** for AWS/S3 access and shared data models.
- **Automation** via GitHub Actions, Fly.io, Netlify, and AWS-managed data storage.

## Highlights
- End-to-end geospatial data platform powering a public dashboard used by civic audiences.
- Vue 3 frontend with MapLibre GL maps, D3.js charts, and Vuetify components.
- Automated ETL pipelines with scheduled refreshes, validation, and S3-backed storage.
- FastAPI service optimized for large GeoJSON payloads with pagination and caching.
- Shared, typed data models across ETL and API for consistent contracts.
- Production deployment on Fly.io (API) and Netlify (frontend) with CI/CD automation.

## Background and data sources
This application began as a civic data dashboard and now runs as an independently maintained public project.

It relies only on public data sources:
- **Shooting victims**: City of Philadelphia open data (OpenDataPhilly.org)
- **Homicide totals**: Philadelphia Police Department crime statistics site
- **Court cases**: Pennsylvania Unified Judicial System web portal

## Methods and caveats
- Shooting victims data is updated daily on OpenDataPhilly (typically by ~10:30am on weekdays).
- Homicide totals include all homicide types, not just firearm-related incidents.
- All data is preliminary and may differ from other public incident datasets.
- Court case matches are derived by searching the DC number in the Philadelphia Municipal Court portal; updates run weekly.

See [docs/data-sources.md](docs/data-sources.md) for source details and caveats.

## Quick start
Prereqs: Python 3.13, `uv`, `just`, AWS CLI, and Fly CLI for API deploys.

1) Create `.env` from `.env.example` and set the AWS region, bucket, and local credential profile.
2) Run the API locally:

```bash
just api-dev
```

3) Run ETL jobs (examples):

```bash
just etl-shootings
just etl-homicides
just etl-courts
just etl-streets
```

4) Pull down S3 data locally (optional):

```bash
just data-sync
```

## Data flow (high level)
1. **ETL** jobs write processed data to S3 (`processed/*.geojson`, `processed/*_meta.json`)
2. **API** loads data from S3 at startup, indexes by year, and caches in memory
3. **Frontend** fetches metadata, then loads year-specific NDJSON data on demand
4. **GitHub Actions** trigger ETL + Fly restart on schedules for freshness

For more detail, see [docs/architecture.md](docs/architecture.md).

## API design
The shootings endpoint uses a versioned, content-addressed caching strategy:
- `GET /shootings/meta` — Returns version hash, available years, and per-year URLs
- `GET /shootings/rows/{version}/{year}.ndjson` — Year-specific data (immutable, cached 1 year)

The frontend builds GeoJSON client-side from the NDJSON rows, avoiding duplicate data transfer.

## Repo structure
```
packages/api/               FastAPI service
packages/etl/               ETL pipelines and CLI
packages/dashboard-utils/   Shared AWS + data utilities + models
packages/aws-batch-scraper/ Reusable ECS/SQS scraper framework
frontend/                    Vue 3 frontend application
```

## Known Limitations

- Source data is preliminary and can change after publication.
- Court matching uses public portal search behavior and may miss cases when source
  systems change, records are delayed, or incident identifiers are absent.
- The courts scraper is intentionally isolated behind SQS/ECS workers because it
  depends on a stateful external portal.
- Infrastructure is documented as runtime contracts rather than checked-in IaC.

## Frontend

The dashboard UI is a Vue 3 single-page application with interactive maps and charts.

**Tech stack:**
- **Vue 3** with Composition API
- **Vuetify 3** for Material Design components
- **MapLibre GL** for interactive mapping
- **D3.js** for data visualizations and charts
- **Arquero** for in-browser data filtering
- **Pinia** for state management
- **Vite** for build tooling

**Project structure:**
```
frontend/src/
├── app/           App shell and layout
├── features/      Feature modules (map, charts, filters)
├── pages/         Route-level page components
├── shared/        Shared utilities, API client, stores
├── types/         TypeScript type definitions
└── main.ts        Application entry point
```

**Development:**
```bash
cd frontend
npm install
npm run dev        # Start dev server at http://localhost:5173
npm run build      # Production build to dist/
```

**Deployment:**
The frontend is deployed to Netlify. Pushes to `main` trigger automatic builds.

## Deployment (Fly.io)
- `fly.toml` defines app config.
- `packages/api/Dockerfile` builds the API image.

```bash
just fly-secrets-api
just fly-deploy-api
```

## Portfolio
If this project is useful or you want to collaborate, check out:
https://nickhand.dev

## Feedback
Please open an issue: https://github.com/nickhand/philly-gun-violence-dashboard/issues
