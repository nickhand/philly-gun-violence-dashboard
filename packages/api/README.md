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

### Health
- `GET /health` — Health check endpoint

## Caching Strategy

The API uses a versioned, content-addressed caching strategy:

1. **Meta endpoint** (`/shootings/meta`) returns a content-based version hash and ETag
2. **Year-specific endpoints** include the version in the URL path, making them immutable
3. Frontend caches versioned URLs for 1 year (`Cache-Control: public, max-age=31536000, immutable`)

## Environment

Required (via `.env` or runtime secrets):
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `AWS_BUCKET_NAME`

Optional:
- `API_REFRESH_TTL_SECONDS` (default: 300) — How often to check S3 for data updates

## Local Development

```bash
just api-dev
```

## Deployment (Fly.io)

```bash
just fly-secrets-api   # Set secrets from .env
just fly-deploy-api    # Deploy to Fly.io
```

