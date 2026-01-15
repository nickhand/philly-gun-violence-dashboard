<img width="500" height="500" src="./frontend/public/og-image.png"/>

# Philadelphia Gun Violence Dashboard

A full-stack data pipeline and API that power a public Gun Violence Dashboard for the City of Philadelphia.
Visit the live map: https://nickhand.dev/philly-gun-violence-map

## What this repo contains
- **Vue 3 dashboard** with interactive maps and data visualizations.
- **FastAPI service** for geospatial endpoints and dashboard data.
- **ETL pipelines** that ingest, clean, and enrich shootings, homicides, courts, and boundaries data.
- **Shared utilities** for AWS/S3 access and shared data models.
- **Automation** via GitHub Actions, Fly.io, and Netlify deployment.

## Highlights
- End-to-end geospatial data platform powering a public dashboard used by civic audiences.
- Vue 3 frontend with MapLibre GL maps, D3.js charts, and Vuetify components.
- Automated ETL pipelines with scheduled refreshes, validation, and S3-backed storage.
- FastAPI service optimized for large GeoJSON payloads with pagination and caching.
- Shared, typed data models across ETL and API for consistent contracts.
- Production deployment on Fly.io (API) and Netlify (frontend) with CI/CD automation.

## Background and data sources
This application was originally developed by Nick Hand for the Philadelphia City Controller’s Office and later migrated to his personal website as a rebuilt, improved version.

It relies only on public data sources:
- **Shooting victims**: City of Philadelphia open data (OpenDataPhilly.org)
- **Homicide totals**: Philadelphia Police Department crime statistics site
- **Court cases**: Pennsylvania Unified Judicial System web portal

## Methods and caveats
- Shooting victims data is updated daily on OpenDataPhilly (typically by ~10:30am on weekdays).
- Homicide totals include all homicide types, not just firearm-related incidents.
- All data is preliminary and may differ from other public incident datasets.
- Court case matches are derived by searching the DC number in the Philadelphia Municipal Court portal; updates run weekly.

## Quick start
Prereqs: Python 3.13, `uv`, `just`, AWS CLI, Fly CLI (for deploys).

1) Create `.env` from `.env.example` and set AWS credentials and bucket.
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
1) ETL jobs write processed data to S3.
2) The API reads from S3 and caches in memory.
3) GitHub Actions trigger ETL + Fly restart for freshness.

## Repo structure
```
api/               FastAPI service
etl/               ETL pipelines and CLI
dashboard-utils/   Shared AWS + data utilities + models
frontend/          Vue 3 frontend application
```

## Frontend

The dashboard UI is a Vue 3 single-page application with interactive maps and charts.

**Tech stack:**
- **Vue 3** with Composition API
- **Vuetify 3** for Material Design components
- **MapLibre GL** for interactive mapping
- **D3.js** for data visualizations and charts
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
- `api/Dockerfile` builds the API image.

```bash
just fly-secrets-api
just fly-deploy-api
```

## Portfolio
If this project is useful or you want to collaborate, check out:
https://nickhand.dev

## Feedback
Please open an issue: https://github.com/nickhand/philly-gun-violence-dashboard/issues
