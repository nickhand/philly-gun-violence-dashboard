# ETL

Data pipelines for the Philadelphia Gun Violence Dashboard. The ETL jobs pull raw sources, clean and enrich them, then write processed datasets to S3.

## Commands

Run from repo root with `just`:

```bash
just etl-shootings    # Update shootings data from OpenDataPhilly
just etl-homicides    # Update homicide totals from PPD crime stats
just etl-courts       # Update court case matches (Playwright scraper)
just etl-streets      # Update street block data
just etl-boundaries   # Update boundary datasets
```

Or run the CLI directly:

```bash
cd etl
uv run gv-dashboard-etl --help
uv run gv-dashboard-etl shootings update
uv run gv-dashboard-etl homicides update
```

## Pipeline Structure

Each domain follows this pattern:
- `cli.py` — Typer command entry point
- `extract.py` — Fetch raw data from public sources
- `transform.py` — Clean, validate, and enrich data
- `load.py` — Write to S3 using `dashboard_utils.processed`
- `pipeline.py` — Orchestrate extract → transform → load

## Notes

- All processed outputs are written to S3 (`processed/*.geojson`, `processed/*_meta.json`)
- GitHub Actions run these on schedules and restart the Fly API to serve fresh data
- Use `--dry-run` to test transforms without writing to S3
- Use `--ignore-checks` to skip validation checks

## Environment

Required (via `.env`):
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `AWS_BUCKET_NAME`

