# ETL

Data pipelines for the Philadelphia Gun Violence Dashboard. The ETL jobs pull raw sources, clean and enrich them, then write processed datasets to S3.

## Commands

Run from repo root with `just`:

```bash
just etl-shootings    # Update shootings data from OpenDataPhilly
just etl-homicides    # Update homicide totals from PPD crime stats
just etl-courts       # Update public court-search observations (Playwright scraper)
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
- The external Fly scheduler dispatches these GitHub Actions workflows. The
  pointer-aware API discovers committed releases through a bounded lazy refresh;
  the workflow restart steps are retained only for the initial compatibility
  rollout and should be removed after that API version is verified in production.
- Use `--dry-run` to test transforms without writing to S3
- Use `--ignore-checks` to skip validation checks
- Use `smoke` commands to check live sources, AWS config, or portal availability
  without writing outputs.

### Boundary releases

`just etl-boundaries` computes and serializes every registered boundary before
writing anything. It uploads the exact GeoJSON bytes under
`reference/boundaries/releases/<release-id>/`, then conditionally replaces
`reference/boundaries_release.json`. The release pointer identifies the complete
dataset set, exact object keys, and SHA-256 checksums. Its release id is derived
from the dataset names and member checksums, so changed bytes create a new
generation even when the names are unchanged.

The pointer update uses the manifest ETag read before extraction. A competing
different publisher therefore fails instead of overwriting the winner. The API
validates every configured key and checksum, builds the entire candidate
off-state, and swaps only the complete generation. The pre-release
`reference/boundaries_manifest.json` schema is retained as a second atomic
compatibility pointer whose string values name the same immutable members.
Stable `reference/<dataset>.geojson` objects remain as compatibility mirrors
and are written only after both pointers; they are not authoritative for the
API or current ETL consumers.

This is a reader-first migration. Deploy and verify an API/ETL build that can
read `boundaries_release.json` before the first updated boundary run. Older API
instances and rollback builds continue to read the unchanged legacy-manifest
schema and its immutable member names, so publishing the new pointer does not
create a rollback cutoff. Do not remove that compatibility pointer until every
supported reader and rollback artifact has migrated.

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
release, and replaces `manifest.json` last. Before extraction, the job captures
the pointer body and ETag. The final PutObject uses `If-Match` (or
`If-None-Match` for the first release) and rejects an equal or older
`(data_through, run_started_at)` generation. A competing writer therefore wins
once; the loser fails and must rerun from the winning manifest so it cannot
regress the pointer or discard its N-1 history. A reader sees either the
complete previous release or the complete new release. Consumers must fetch the
stable manifest and use each `downloads[].path`; they must not build a data URL
from a filename. During the schema-version-1 migration, the frontend accepts
both the old stable paths and the new manifest-driven version-2 paths.

The same manifest now contains an additive `application_data` section naming
checksummed, immutable processed GeoJSON and metadata under
`processed/shootings/releases/<release-id>/`. It is therefore the single release
pointer for both public downloads and API rows; those views cannot advance to
different shooting releases. The job writes legacy processed object names as
compatibility mirrors only after moving the pointer. A pointer-aware API never
uses those mirrors after the first pointed release, including while the first
mirror pair is being updated. Each new manifest also carries the former
`application_data` as `previous_application_data`, providing a bounded N-1 row
version even across API restarts.

Homicide totals use the equivalent
`processed/homicides/release.json` pointer for immutable totals and metadata.
The job also captures the exact body and ETag of the daily-history CSV before
extraction and conditionally replaces only that revision. The daily history is
written before the release pointer because it is input to the next ETL run; an
overlapping stale job cannot overwrite a newer history revision. The API-facing
totals/metadata compatibility mirrors follow the pointer and are never
authoritative for a pointer-aware API.

Roll out pointer support in this order: deploy and verify the API first, complete
and verify the courts semantics-v2 migration described below, then run the first
new shootings publication. The API may deploy before the courts migration, but
the shootings job must not publish the historical unversioned false flags. This
ordering lets the new API fall back safely before the first pointer exists and
prevents an older API build from observing compatibility mirrors
mid-publication. Do not delete stable mirrors yet; other ETL readers and rollback
builds still use them.

Each manifest entry includes a stable dataset id and label, file name, kind,
media type, byte size, SHA-256 checksum, and row count. Geography entries also
include the internal dataset name and the exact shooting-record `join_field`.
This is the canonical inventory for the Data page. The publication step rejects
blank or duplicate reference join keys, missing or invalid geometries, and any
nonblank shooting join value absent from its companion reference file.

Immutable release objects use a one-year browser/CDN cache policy. During this
rollout, do not apply expiration rules to `public/downloads/releases/*`,
`processed/shootings/releases/*`, `processed/homicides/releases/*`, or
`reference/boundaries/releases/*`. A fixed age rule can eventually delete a
still-current release if an ETL stops, and a second lifecycle rule cannot
override that expiration. Add garbage collection only after it is pointer-aware
and explicitly protects every current, previous, and still-cacheable public
release. Serve only `public/downloads/*` through CloudFront or a storage read
policy; never expose the private `processed/` or `reference/` prefixes.

#### GitHub Actions IAM

The shootings workflow assumes
`arn:aws:iam::985454606291:role/gha-ujs-scraper`, not the local
`nick-philly-gv-dashboard` IAM user. Keep the role's existing `PutObject`
permissions for the stable manifest and immutable public release prefix. Add
this separate read-only statement before running the workflow:

```json
{
  "Sid": "ReadAtomicShootingsManifest",
  "Effect": "Allow",
  "Action": "s3:GetObject",
  "Resource": "arn:aws:s3:::philly-gun-violence-dashboard/public/downloads/manifest.json"
}
```

`GetObject` is required on the stable manifest so a new publication can carry
its current `application_data` forward as the bounded N-1 API release. It is not
used to enumerate the bucket.

The role still needs read/write permissions for the configured processed and
reference prefixes, including the shootings, homicide, and boundary immutable
release prefixes, their stable pointers, and their compatibility mirrors.
Verify those exact paths with IAM policy simulation before rollout. Its GitHub
OIDC trust policy must allow
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
gv-dashboard-etl courts worker
```

The scraper needs existing ECR, ECS, SQS, IAM, and separate worker/monitor task
definition resources.
The image is built and pushed by the user or CI:

```bash
SCRAPER_IMAGE_TAG=$(git rev-parse HEAD) \
  just scraper-build-and-push-container
```

The recipe requires a clean checkout and the full current commit SHA, refuses a
tag that already exists, verifies the local revision label, resolves the pushed
digest, waits for its scan, and blocks any Critical or High finding. Configure
the ECR repository itself with immutable tags and scan-on-push before using the
recipe; immutability remains an external rollout gate that closes the
check-then-push race. Use the printed `repository@sha256:...` URI in separate
worker and monitor ECS task-definition revisions. Only the monitor definition
may reference the GitHub dispatch-token secret.

The image runs as the unprivileged `app` user and keeps application code,
dependencies, and Chromium root-owned. Both task definitions must explicitly
set `user: app`, set `readonlyRootFilesystem: true`, and mount a writable task
volume at `/tmp`;
`HOME`, `TMPDIR`, and the XDG cache/config paths already point there. CI starts
Chromium with a read-only root plus a temporary `/tmp` mount so this contract is
tested before release. The image declares `VOLUME ["/tmp"]` after preserving
mode `1777`; the task volume must mount at that exact path so Fargate carries
those writable sticky-directory permissions into the otherwise empty bind mount.

### Courts worker protocol rollout gate

The run-scoped result protocol must not be mixed with the former worker image,
which wrote only global result objects. Before the first run after this change:

1. Use a scheduler quiet window and confirm the `ujs-scraper` ECS cluster has no
   running tasks and the `ujs-incidents` queue's visible, in-flight, and delayed
   counts are all zero. Do not rely on queue depth alone while an old task is live.
2. Build and push a versioned image as above. Register separate worker and
   monitor task-definition revisions that use the printed digest URI, then use
   `aws ecs describe-task-definition` to verify both resolved `image` values
   contain that exact `@sha256:` digest. The worker definition must not contain
   `GITHUB_DISPATCH_TOKEN`; the monitor definition may. A separate worker
   execution role that cannot read the backing secret is recommended as a
   follow-up least-privilege boundary. Set the GitHub Actions repository variable
   `ECS_TASK_DEFINITION` to the exact worker revision and
   `ECS_MONITOR_TASK_DEFINITION` to the distinct exact monitor revision (or
   their full revisioned ARNs). Bare families and one shared revision are
   intentionally rejected. The courts workflow runs a read-only semantic
   preflight before submission; its OIDC role needs
   `ecs:DescribeTaskDefinition` in a separate `Resource: "*"` statement without
   an `ecs:cluster` condition.
   Set `GITHUB_WORKFLOW_FILE=courts-process.yml` for a local generic monitor;
   `CourtsSubmitterConfig` supplies that target to ECS automatically. The
   monitor's fine-grained `GITHUB_DISPATCH_TOKEN` needs repository **Actions:
   read and write**, not **Contents: write**. Do not remove the old event
   listener while any old monitor task is still running: complete the quiet
   window and task/queue checks first, then deploy both new task definitions and
   the workflow together.
3. Run a forced sample with the coordinator enabled:

   ```bash
   just scraper-submit --force --sample 10 --monitor-in-ecs
   ```

4. Before enabling the full external Fly dispatch again, verify the sample run
   wrote `ujs-scraper/runs/<run-id>/results/*.json` (or run-scoped failure JSON),
   every object carries that run ID, the queue drained, processing completed,
   the flags CSV and courts metadata record court-search semantics version 2,
   and the active lease reached a terminal record.

Version 2 is also a data migration boundary. Historical `False` flags cannot be
trusted because the former pipeline filled failed, missing, and unsearched rows
with false. On the first version-2 processing run, historical `True` evidence is
retained, historical false becomes blank/unknown, and only a current run-scoped
result produced from the portal's explicit no-results marker can write false.
The flags CSV carries `court_search_semantics_version=2` on every row and the
courts `meta.json` records the same version, so subsequent partial runs may
safely preserve a versioned false without reviving legacy values.

This migration is a release gate for shootings, not for the API deployment.
Deploy and verify the pointer-aware API first if desired, but do not run the
first new shootings publication until a courts processing run has written and
you have verified semantics version 2 in both the flags CSV and courts metadata.
The shootings transform independently fails closed by converting any remaining
unversioned false to unknown, but that safeguard is not a substitute for the
ordered migration.

The courts Actions workflows intentionally remain `workflow_dispatch`-driven.
The external Fly scheduler starts `courts-scrape.yml`; after terminal queue and
task proof, the credential-isolated ECS monitor starts `courts-process.yml`
with its required `run_id` input. The external scheduler avoids GitHub's
inactivity shutdown for scheduled workflows.

Court processing publishes the owned scrape run's flags and diagnostics; it
does not rewrite or advance the authoritative shootings release. New court
search observations therefore become public with the next shootings ETL
publication. Restarting the API cannot make them visible sooner, so the courts
process workflow does not require a Fly token or restart the API.

## Environment

Required configuration:
- `AWS_REGION`
- `S3_BUCKET` or `AWS_BUCKET_NAME`
- `S3_PROCESSED_PREFIX` (default: `processed`)
- `S3_REFERENCE_PREFIX` (default: `reference`)

AWS credentials are resolved through boto3's default credential chain. Use
`AWS_PROFILE` locally; GitHub Actions and ECS should use OIDC or task roles.
