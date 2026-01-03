# dashboard-utils

Shared utilities and models used across the API and ETL.

## What’s inside
- AWS/S3 helpers for reading/writing data
- Shared Pydantic models (GeoJSON + domain schemas)
- Processed dataset helpers (`read_processed_*`, `write_processed_*`)
- Constants and path helpers

## Usage
This package is used as a local dependency in `api/` and `etl/` via `uv`.

```bash
# from repo root
cd dashboard-utils
uv run python -c "import dashboard_utils"
```

## Key modules
- `dashboard_utils.aws` — S3 client + read/write helpers
- `dashboard_utils.models` — shared Pydantic models
- `dashboard_utils.processed` — S3-first dataset helpers
- `dashboard_utils.paths` — S3 key helpers

