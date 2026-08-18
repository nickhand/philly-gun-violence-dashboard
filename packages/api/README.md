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
- `GET /health` — Health check endpoint

## Caching Strategy

The API uses a versioned, content-addressed caching strategy:

1. **Meta endpoint** (`/shootings/meta`) returns a content-based version hash and ETag
2. **Year-specific endpoints** include the version in the URL path, making them immutable
3. Frontend caches versioned URLs for 1 year (`Cache-Control: public, max-age=31536000, immutable`)

The statistics JSON, HTML, and sitemap share one snapshot rendered after
startup. They are invalidated when either the shooting or homicide cache
refreshes, use ETags for revalidation, and preserve the distinct freshness date
for each dataset.

## Environment

Required configuration:
- `AWS_REGION`
- `S3_BUCKET` or `AWS_BUCKET_NAME`
- `S3_PROCESSED_PREFIX` (default: `processed`)

AWS credentials are resolved through boto3's default credential chain. Use
`AWS_PROFILE` locally; use runtime secrets, OIDC, or instance/task roles in
deployed environments.

Optional:
- `API_REFRESH_TTL_SECONDS` (default: 300) — How often to check S3 for data updates

## Local Development

```bash
just api-dev
```

Audit every visible stats-page figure, table row, freshness date, JSON-LD answer,
and sitemap date against the API payloads:

```bash
python scripts/audit_stats_consistency.py http://127.0.0.1:8000
```

## Deployment (Fly.io)

```bash
just fly-secrets-api   # Set secrets from .env
just fly-deploy-api    # Deploy to Fly.io
```
