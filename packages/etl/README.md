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

### Public downloads

The shootings job publishes the cleaned record-level CSV and its matching map
reference files as one release. The public set includes ZIP codes,
neighborhoods, police and City Council districts, Pennsylvania House and Senate
districts, elementary school catchments, and dashboard-derived street blocks.
It excludes city limits and raw street centerlines because the shooting download
has no field that joins to those files.

`public/downloads/manifest.json` is the only stable public object name. Manifest
schema version 2 points to all nine files under a content-addressed path:

```text
public/downloads/releases/<release-id>/philadelphia-shooting-victims.csv
public/downloads/releases/<release-id>/geography/<reference-file>.geojson
```

The ETL serializes and validates every file first, uploads the complete immutable
release, and replaces `manifest.json` last. S3 replaces that one small object
atomically. A reader therefore sees either the complete previous release or the
complete new release, even if a job fails or two jobs overlap. Consumers must
fetch the stable manifest and use each `downloads[].path`; they must not build a
data URL from a filename. During the schema-version-1 migration, the frontend
accepts both the old stable paths and the new manifest-driven version-2 paths.

Each manifest entry includes a stable dataset id and label, file name, kind,
media type, byte size, SHA-256 checksum, and row count. Geography entries also
include the internal dataset name and the exact shooting-record `join_field`.
This is the canonical inventory for the Data page. The publication step rejects
blank or duplicate reference join keys, missing or invalid geometries, and any
nonblank shooting join value absent from its companion reference file.

Immutable release objects use a one-year browser/CDN cache policy. Keep old
release prefixes for at least as long as a cached manifest can be served; a
bucket lifecycle rule may remove substantially older releases. Serve only
`public/downloads/*` through CloudFront or a storage read policy. Do not expose
the private `processed/` or `reference/` prefixes.

#### GitHub Actions IAM

The shootings workflow assumes
`arn:aws:iam::985454606291:role/gha-ujs-scraper`, not the local
`nick-philly-gv-dashboard` IAM user. Add this statement to the role's existing
identity policy before running the workflow:

```json
{
  "Sid": "PublishPublicDownloadV2",
  "Effect": "Allow",
  "Action": "s3:PutObject",
  "Resource": [
    "arn:aws:s3:::philly-gun-violence-dashboard/public/downloads/manifest.json",
    "arn:aws:s3:::philly-gun-violence-dashboard/public/downloads/releases/*"
  ]
}
```

The role still needs its existing read/write permissions for the configured
processed and reference prefixes. Its GitHub OIDC trust policy must allow
`sts:AssumeRoleWithWebIdentity` from
`arn:aws:iam::985454606291:oidc-provider/token.actions.githubusercontent.com`,
require the audience `sts.amazonaws.com`, and restrict the subject to this
repository. For production runs from the default branch, use:

```json
{
  "StringEquals": {
    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
    "token.actions.githubusercontent.com:sub":
      "repo:nickhand/philly-gun-violence-dashboard:ref:refs/heads/main"
  }
}
```

The workflow already requests `id-token: write` and names this role explicitly.
Use `aws sts get-caller-identity` in the workflow log to confirm the assumed role
before diagnosing S3 access. IAM changes are made outside this repository.

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
