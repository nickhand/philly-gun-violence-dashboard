# ETL

Data pipelines for the Philadelphia Gun Violence Dashboard. The ETL jobs pull raw sources, clean and enrich them, then write processed datasets to S3.

## Commands

Run from repo root with `just`:

```bash
just etl-shootings    # Update shootings data from OpenDataPhilly
just etl-homicides    # Update homicide totals from PPD crime stats
just etl-courts       # Update court case matches (Playwright scraper)
just etl-shootings-smoke
just etl-homicides-smoke
just etl-courts-smoke
just etl-streets      # Update street block data
just etl-boundaries   # Update boundary datasets
```

Or run the CLI directly:

```bash
cd packages/etl
uv run gv-dashboard-etl --help
uv run gv-dashboard-etl shootings update
uv run gv-dashboard-etl shootings smoke
uv run gv-dashboard-etl homicides update
uv run gv-dashboard-etl homicides smoke
uv run gv-dashboard-etl courts smoke
```

## Pipeline Structure

Each domain follows this pattern:
- `cli.py` — Typer command entry point
- `extract.py` — Fetch raw data from public sources
- `transform.py` — Clean, validate, and enrich data
- `load.py` — Write to S3 using `dashboard_utils.processed`
- `pipeline.py` — Orchestrate extract → transform → load

## Notes

- All processed outputs are written to S3 under the configured processed prefix.
  Each core dataset also writes a `meta.json` with status, `last_updated`,
  `data_through`, schema version, row counts, and source-specific health fields.
- GitHub Actions run these on schedules and restart the Fly API to serve fresh data
- Use `--dry-run` to test transforms without writing to S3
- Use `--ignore-checks` to skip validation checks
- Use `smoke` commands to check live sources, AWS config, or portal availability
  without writing outputs.

## Courts Scraper

The courts scraper is this repository's implementation of the generic
`aws-batch-scraper` framework. The framework lives outside the courts package;
UJS-specific names such as `ujs-scraper`, `ujs-incidents`, and
`gv-dashboard-etl courts worker` are this project's configuration, not framework
defaults.

The courts container is `packages/etl/Dockerfile`. It is intentionally project-specific:
it installs `dashboard-utils`, `etl`, and Playwright Chromium, then defaults to:

```bash
uv run gv-dashboard-etl courts worker
```

The scraper needs existing ECR, ECS, SQS, IAM, and task definition resources.
The image is built and pushed by the user or CI:

```bash
just scraper-build-and-push-container
```

## Environment

Required configuration:
- `AWS_REGION`
- `S3_BUCKET` or `AWS_BUCKET_NAME`
- `S3_PROCESSED_PREFIX` (default: `processed`)
- `S3_REFERENCE_PREFIX` (default: `reference`)

AWS credentials are resolved through boto3's default credential chain. Use
`AWS_PROFILE` locally; GitHub Actions and ECS should use OIDC or task roles.
