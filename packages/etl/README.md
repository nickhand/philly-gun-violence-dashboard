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

`gv-dashboard-etl courts fargate-smoke` is a container-only promotion probe;
run it as the command override of one exact digest-backed worker task, as
described under **Courts Scraper** below.

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

The courts container is `packages/etl/Dockerfile`. It is intentionally
project-specific. The final image starts from an exact `linux/amd64` manifest
of Ubuntu 26.04 LTS, which ECR scanning supports. Every apt transaction uses the
same signed, dated Ubuntu snapshot, and the build refuses an overridden snapshot
date. The pinned snapshot includes Canonical's `libcurl3t64-gnutls`
`8.18.0-1ubuntu2.4` security update from USN-8651-1; the image build and SBOM
gate both assert that exact package version.
<!-- BEGIN GENERATED: chrome-lock-product-version -->
It full-upgrades that snapshot before installing Ubuntu's native Python
(3.13 or newer) and a checksum-pinned Google Chrome 152.0.7977.82 package.
<!-- END GENERATED: chrome-lock-product-version -->
The Playwright client is pinned to 1.62.0, launches the system `chrome` channel
and never downloads a separate browser bundle. The courts worker explicitly
sets `chromium_sandbox=False`: Fargate's default seccomp profile does not permit
the namespace operations required by Chrome's nested sandbox. This exception is
local to the Fargate courts scraper; the host-run homicide workflow continues to
set `chromium_sandbox=True`. uv cannot download a different interpreter. CI
verifies those versions and launches Chrome as the production user under the
same default outer seccomp behavior used by Fargate. The resulting release
artifact is identified by its own immutable ECR digest, and its scan remains the
fail-closed vulnerability gate.

`chrome-lock.json` is the authoritative Chrome package and executable contract.
After changing that lock, run
`python3 packages/etl/scripts/render_chrome_lock.py --write` from the repository
root to update its checked-in consumers. CI runs the same command with `--check`
to reject missing markers, unexpected consumer structure, and generated drift.

The Fly scheduler dispatches the `Chrome stable update` workflow every morning.
It authenticates Google's signed repository metadata, downloads and verifies
the selected package, refreshes the lock and all generated consumers, and opens
or updates one automation pull request. It dispatches the complete ETL and
repository-configuration suites on the exact update commit. A passing, strictly
newer release within the current Chrome milestone is merged automatically; a
new milestone or same-version republish remains open for review. Production
smoke tests are independent of Chrome release drift, while scheduled ETL runs
consume the reviewed lock instead of failing merely because Google published a
newer release. The repository's Actions settings must allow `GITHUB_TOKEN` to
create pull requests; an optional
`CHROME_UPDATE_TOKEN` secret can supply a dedicated bot token instead.

The browser context blocks service workers and intercepts every routed page
request. It permits only HTTPS requests to the exact
`ujsportal.pacourts.us` origin on the default TLS port, aborts and records every
attempted origin escape, blocks every WebSocket, and checks the final page
origin after the landing page and every search. Live landing and search
observations used to establish this policy required neither third-party origins
nor WebSockets. A newly required origin or WebSocket is therefore a failing
policy change to investigate and review, not something the worker follows
implicitly.

The minimal Ubuntu base does not initially contain CA roots. Before its first
apt transaction, the build bootstraps `openssl` 3.5.5-1ubuntu3.3 (SHA-256
`c1f53878bdada693da7fb64a28c06b7dd65a43b8452e6fcad670c0d09c77f293`)
and `ca-certificates` 20260601~26.04.1 (SHA-256
`6077d27c6b6f8b23590cb01ff877ed8c804a67a5442cc32b5a33da10d2bd0e90`)
from exact Canonical snapshot URLs. Those artifacts and hashes come from the
Ubuntu `resolute-security` Packages index whose InRelease is signed by the
Ubuntu archive key. The build clears inherited package lists, treats any
snapshot update warning as an error, and verifies indexes for every configured
suite before upgrading or installing packages. This prevents apt from silently
falling back to live indexes when the requested snapshot is unavailable.

The image defaults to:

```bash
gv-dashboard-etl courts worker
```

The image has an explicitly empty entrypoint and contains an executable
`/bin/false` that returns status 1. Keep the worker task definition on the image
default command. Set the distinct monitor task definition's default command to
exactly `["/bin/false"]`; the framework supplies the real monitor command only as
a reviewed `RunTask` override. A monitor launched without that override therefore
fails immediately instead of accidentally starting another worker or letting an
image entrypoint consume the inert command.

The scraper needs existing ECR, ECS, SQS, IAM, and separate worker/monitor task
definition resources.
The image is built and pushed by the user or CI:

```bash
SCRAPER_IMAGE_TAG=$(git rev-parse HEAD) \
  just scraper-build-and-push-container
```

The recipe requires a clean checkout and the full current commit SHA, refuses a
tag that already exists, verifies the local revision label, and runs pinned Syft
and Grype containers before any push. The database download cannot see the image;
SBOM generation and vulnerability matching have no network, Docker socket,
registry credentials, ignore rules, or VEX. The gate requires exact Playwright,
Chrome deb, Playwright Node, and Chrome executable identities. Because Syft
records system Chrome as a deb, a separate exact Google Chrome CPE report covers
NVD browser findings. A known-vulnerable Chrome control must produce Critical
and High matches before the current Chrome CPE can pass. The executable digest
is compared with the value derived from the checksum-pinned deb payload.

The recipe then tags the exact scanned image ID, confirms ECR's pushed manifest
uses that config digest, and polls the remote scan for about 30 minutes. Any
Critical, High, or Unknown local finding and any Critical or High ECR finding
blocks release, including findings without fixes. Authorization, terminal scan,
malformed-response, stale-database, and timeout failures exit nonzero without
printing an image URI. Configure ECR with immutable tags and scan-on-push before
using the recipe. Use the printed
`repository@sha256:...` URI in separate worker and monitor ECS task-definition
revisions. Only the monitor definition may reference the GitHub dispatch-token
secret.

The image runs as the unprivileged `app` user and keeps application code,
dependencies, and Google Chrome root-owned. Both task definitions must explicitly
target `LINUX/X86_64` with `awsvpc`, contain only the reviewed container, set
`user: app`, set `readonlyRootFilesystem: true`, remain unprivileged, drop
`ALL` Linux capabilities while adding none, use no security-profile overrides
or opaque mounts, and mount one
ephemeral writable task volume only at `/tmp`;
`HOME`, `TMPDIR`, and the XDG cache/config paths already point there. CI starts
Chrome with a read-only root plus a temporary `/tmp` mount so this contract is
tested before release. The image declares `VOLUME ["/tmp"]` after preserving
mode `1777`; the task volume must mount at that exact path so Fargate carries
those writable sticky-directory permissions into the otherwise empty bind mount.

The CI browser smoke keeps Docker's default seccomp profile and explicitly uses
`chromium_sandbox=False`, matching the courts worker's browser and outer-seccomp
settings rather than relaxing the container boundary. CI additionally gives its
temporary mount `nosuid`, `nodev`, and `noexec` flags; those stricter local flags
are not asserted as properties of Fargate's task bind mount. Because the internal
browser sandbox is disabled, a successful Chrome exploit means same-user code
execution as the courts worker. The exact-origin route and final-URL policy
constrains ordinary Playwright HTTP(S) requests and blocks browser WebSockets;
it is defense-in-depth, not a kernel or network containment boundary. It does
not contain WebRTC, raw sockets, or network activity after same-user code
execution. Exploit code is not bound by that route.
With the currently accepted all-egress security group, it could contact arbitrary
outbound endpoints, query the ECS task-credential endpoint, exfiltrate temporary
task-role credentials, read or irrecoverably overwrite unversioned
`ujs-scraper/*` S3 objects, drain the main SQS queue, or spam its DLQ. This risk is
knowingly accepted for now; the portal is not trusted content. Real outbound
containment requires a dedicated egress proxy or firewall plus a reviewed VPC
endpoint design, not another browser callback.

Compensating controls still reduce likelihood and blast radius: a patched,
checksum-pinned and vulnerability-scanned Chrome image; immutable image digests;
Fargate task isolation and its default security profile; an unprivileged `app`
user; a read-only root; all Linux capabilities dropped; and only one ephemeral
writable mount at `/tmp`. The Chrome sandbox helper is removed from the image
rather than retaining an unused setuid-capable executable. After all installs,
the build also strips every SUID and SGID file mode across the image and fails if
any remain; CI repeats that whole-filesystem assertion in a read-only,
network-disabled inspection container. The audit runs as root only so owner-only
directories cannot hide a privileged mode; production still runs as `app` with
all capabilities dropped. The worker receives no GitHub dispatch secret; only
the non-browser monitor task may receive it through ECS `secrets`.

Before promoting worker/monitor revisions, run the exact digest as one one-shot
Fargate task using the production worker task definition, subnets, security
groups, task/execution roles, and this command override:

```text
gv-dashboard-etl courts fargate-smoke
```

Supply the same nonsecret overrides as a production worker launch:
`AWS_ACCOUNT_ID`, `AWS_REGION`, `ECS_CLUSTER_NAME`, the exact revisioned
`ECS_TASK_DEFINITION`, digest-pinned `ECS_EXPECTED_IMAGE_URI`,
`ECS_CONTAINER_NAME`, and `ECS_PLATFORM_VERSION=1.4.0`. Fargate injects
`ECS_CONTAINER_METADATA_URI_V4`; do not synthesize it. The command reads that
link-local endpoint, makes no AWS API calls, and writes no application data. It
binds the live Fargate launch, cluster, task family/revision, only application
container, image URI, and image digest to those overrides. It also fails unless
the live process is the non-root `app` user; seccomp filter mode is 2; effective,
permitted, and bounding capability sets are zero; the root mount is read-only;
`/tmp` is a separate writable mode-1777 mount; the Chrome sandbox helper and
reachable SUID/SGID files are absent; and `GITHUB_DISPATCH_TOKEN` is absent. It
then uses the real `UJSPortalScraper` to reach the live landing selector under
the exact-origin policy and, while the browser is open, proves that a Chrome
process has the explicit `--no-sandbox` argument.

Promote only when the task exits zero and its logs contain this marker exactly
once:

```text
COURTS_FARGATE_SMOKE_OK_V1
```

Any missing marker or nonzero exit blocks promotion. Do not loosen the Fargate
security profile, add privileges, or fall back to a different task definition
to make the probe pass.

The in-container metadata does not expose the exact Fargate platform version,
`enableExecuteCommand`, task-definition security fields, or authoritative ENI
security groups. Pair the marker with mandatory control-plane evidence for the
same returned task ARN. Before launch, `DescribeTaskDefinition` must resolve the
exact ACTIVE worker ARN/revision and prove Fargate compatibility,
`LINUX/X86_64`, the exact digest image and container, all reviewed isolation
fields, and no worker secret channel. Launch exactly one task with launch type
Fargate, platform version `1.4.0`, execute-command disabled, and the production
subnets/security groups. Afterward, `DescribeTasks` must show that exact task
definition ARN, `FARGATE`, Linux platform `1.4.0`,
`enableExecuteCommand=false`, the exact container/image/`imageDigest`, the
expected attached ENI and subnet, `STOPPED`, and exactly one configured essential
container with exit code 0. Resolve the ENI with EC2 and compare its complete
security-group set. CloudWatch must contain the success marker exactly once, and
ECS must show no remaining PENDING or RUNNING probe task. Any mismatch blocks
promotion even if the in-container marker appeared.

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
   `GITHUB_DISPATCH_TOKEN`; the monitor definition may. A distinct worker
   execution role that cannot read the backing secret is a future
   least-privilege improvement, but current preflight requires both definitions
   to use `ECS_EXPECTED_EXECUTION_ROLE_ARN`. Do not configure separate execution
   roles until distinct expected-role settings and validation are implemented.
   Set the GitHub Actions repository variable
   `ECS_TASK_DEFINITION` to the exact worker revision and
   `ECS_MONITOR_TASK_DEFINITION` to the distinct exact monitor revision (or
   their full revisioned ARNs), and set `ECS_EXPECTED_IMAGE_URI` to the exact
   ECR `repository@sha256` URI printed by the completed release gate. Bare
   families, one shared revision, and a task definition using any other image
   are intentionally rejected. The monitor definition must default exactly to
   `["/bin/false"]`, while the worker must retain the image's worker default; both
   rely on the image's empty entrypoint. The courts workflow also requires
   `ECS_EXPECTED_TASK_ROLE_ARN` and
   `ECS_EXPECTED_EXECUTION_ROLE_ARN` to match the exact reviewed same-account
   roles in both definitions, and set `ECS_EXPECTED_MONITOR_SECRET_ARN` to the
   exact dispatch-token secret ARN used once by the monitor definition. Every
   launch pins `ECS_PLATFORM_VERSION=1.4.0`. The courts workflow runs a read-only semantic
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
   and the active lease reached a successful terminal record. Its manifest must
   record `selection_mode=sample`, the original `candidate_count`, and its
   selected `input_size`. Sample and incremental processing validate their
   completed exact-run artifacts but intentionally do not read or write stable
   `processed/courts/portal_results.json`,
   `processed/courts/scraped_courts_data.csv`, or courts metadata.

5. Submit a no-sample forced run for production publication. Only this path is
   recorded as `selection_mode=full`, and its manifest is accepted only when
   `candidate_count == input_size`. Verify the resulting flags CSV and courts
   metadata before allowing a shootings publication to consume them.

Version 2 is also a data migration boundary. Historical `False` flags cannot be
trusted because the former pipeline filled failed, missing, and unsearched rows
with false. On the first version-2 processing run, historical `True` evidence is
retained, historical false becomes blank/unknown, and only a current run-scoped
result produced from the portal's explicit no-results marker can write false.
The flags CSV carries `court_search_semantics_version=2` on every row and the
courts `meta.json` records the same version.

Run selection is an explicit publication boundary. Every immutable run manifest
records `selection_mode` (`sample`, `incremental`, or `full`), the complete
pre-selection `candidate_count`, and its selected `input_size`. Sample and
incremental processing validate their exact-run results but never replace
`portal_results.json`, the stable flags CSV, or courts metadata. Only a forced,
unsampled `full` run can publish them, and it must prove that candidate and input
counts match and that every input has exactly one terminal result or failure
record. Failed and inconclusive searches remain unknown; complete coverage means
the full input snapshot was accounted for, not that every portal search was
conclusive.

The stable courts metadata binds that full run to its flags with
`publication_contract_version`, `run_id`, `selection_mode`, `candidate_count`,
`input_count`, `result_count`, `coverage_complete`, `flags_row_count`, and a
canonical `flags_sha256`. The shootings transform checks all of these fields,
requires semantics version 2 on every flags row, and recomputes the digest before
it can publish. Missing, legacy, sampled, incomplete, or mismatched provenance
fails closed before a shootings release is written. Shootings first reported
after the full-run input snapshot are intentionally left unknown by the left
join until a later full scrape; they do not invalidate the already proven full
snapshot.

Courts metadata also records `result_conflict_policy_version`, total/resolved/
unresolved result-conflict counts, and a deterministic
`result_conflict_evidence_sha256`. Publication contract version 2 requires the
supported conflict policy, reconciled nonnegative counts, zero unresolved
conflicts, zero invalid/orphan resolution objects, and a lowercase SHA-256
evidence digest. A resolved count never means evidence was removed: it requires
an explicit reviewed, append-only accept-canonical record bound to the exact
conflict and canonical bodies. Missing, malformed, tampered, or merely inferred
resolution evidence remains a hard publication block.

This migration is a release gate for shootings, not for the API deployment.
Deploy and verify the pointer-aware API first if desired, but do not run the
first new shootings publication until a courts processing run has written and
you have verified a complete full-run publication contract in both the flags
CSV and courts metadata. The shootings transform independently enforces this
contract; there is no override that turns sampled or unproven court flags into a
shootings release.

The courts Actions workflows intentionally remain `workflow_dispatch`-driven.
The external Fly scheduler starts `courts-scrape.yml`; after terminal queue and
task proof, the credential-isolated ECS monitor starts `courts-process.yml`
with its required `run_id` input. The external scheduler avoids GitHub's
inactivity shutdown for scheduled workflows.

Full courts submissions have a 24-hour duplicate guard. An already-active full
run or a full run whose processing lease reached typed terminal success inside
that interval exits cleanly before SQS, S3, or ECS mutation. Candidate-count
drift is logged, while shootings added later that day remain unknown until the
next weekly scrape. Sample, incremental, failed, legacy-untyped, and incomplete
runs cannot suppress a full scrape. For an intentional emergency repeat,
manually dispatch `courts-scrape.yml` with `allow_recent_full_run=true`; the
override is rejected for sample runs.

Court processing publishes the owned full scrape run's flags and diagnostics;
sample and incremental runs terminate successfully without changing those
stable processed objects. It does not rewrite or advance the authoritative
shootings release. New court search observations therefore become public with
the next shootings ETL publication. Restarting the API cannot make them visible
sooner, so the courts process workflow does not require a Fly token or restart
the API.

## Environment

Required configuration:
- `AWS_REGION`
- `S3_BUCKET` or `AWS_BUCKET_NAME`
- `S3_PROCESSED_PREFIX` (default: `processed`)
- `S3_REFERENCE_PREFIX` (default: `reference`)

AWS credentials are resolved through boto3's default credential chain. Use
`AWS_PROFILE` locally; GitHub Actions and ECS should use OIDC or task roles.
