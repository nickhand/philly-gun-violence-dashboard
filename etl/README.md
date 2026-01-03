# ETL

Data pipelines for the Philadelphia Gun Violence Dashboard. The ETL jobs pull raw sources, clean and enrich them, then write processed datasets to S3.

## Commands
Run from repo root with `just`:

```bash
just etl-shootings
just etl-homicides
just etl-courts
just etl-streets
just etl-boundaries
```

## Notes
- All processed outputs are written to S3 (no local `data/` dependency).
- GitHub Actions run these on schedules and restart the Fly API to serve fresh data.

## Local development
```bash
cd etl
uv run gv-dashboard-etl --help
```

