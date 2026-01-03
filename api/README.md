# API

FastAPI service for the Philadelphia Gun Violence Dashboard. Provides GeoJSON endpoints and summary statistics, backed by S3.

## Key endpoints
- `GET /health`
- `GET /shootings?year=YYYY&limit=2000&offset=0`
- `GET /shootings/years`
- `GET /streets?segment_id=...&limit=2000&offset=0`
- `GET /boundaries` and `GET /boundaries/{dataset}`
- `GET /homicides/{year}`

## Pagination
Endpoints that return large GeoJSON payloads use `limit` and `offset`, and return pagination metadata:
```
limit, offset, count, total, next_offset
```

## Environment
Required (via `.env` or runtime secrets):
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `AWS_BUCKET_NAME`

Optional:
- `API_REFRESH_TTL_SECONDS` (default: 300)

## Local development
```bash
just api-dev
```

## Production
```bash
just api-run
```

## Deployment (Fly.io)
```bash
just fly-secrets-api
just fly-deploy-api
```

