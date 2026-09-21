# Selective same-run recovery

An interrupted full scrape should be resumed from its exact-run S3 checkpoint,
not submitted again under a new run ID. The recovery command inventories the
immutable `input.jsonl`, conclusive `results/`, permanent `failures/`, and
append-only terminal-candidate/conflict evidence before it considers SQS or ECS
mutations.

Start with the default read-only preview:

```console
gv-dashboard-etl courts resume 2026-08-20T140430Z-0116
```

The preview fails closed when:

- the input object lacks an ETag, differs from its manifest SHA-256 anchor, is
  malformed, or contains duplicate IDs;
- a result or failure has an invalid identity/status, is absent from the input,
  or overlaps the other terminal prefix;
- any exact-run result or failure conflict remains unresolved under the reviewed
  conflict policy, or any conflict/resolution evidence is malformed, orphaned,
  or no longer matches its exact retained bodies;
- a content-addressed terminal candidate is malformed, belongs to another
  run/input, or semantically disagrees with the canonical result/failure. Every
  disagreement needs an explicit digest-bound human review: either the existing
  result-conflict `accept-canonical` record or an `accept-decision` record bound
  to the exact terminal decision, canonical body, and rejected candidate body.
  A machine-written terminal-decision conflict is diagnostic evidence, not an
  adjudication. A later third candidate therefore blocks independently until it
  is reviewed too;
- a previously recorded worker task is not `STOPPED`, or is missing without
  a durable terminal observation or explicit reviewed retirement;
- visible, in-flight, and delayed SQS estimates do not remain unchanged across
  the 60-second quiet window, or work remains in flight after recorded workers
  stop;
- a completed/dispatched manifest has missing coverage or a nonempty main
  queue. Scraper recovery never re-enters a completed run.

If the original submission definitively launched zero workers, its typed
`submission-recovery.json` evidence permits recovery without a `tasks.json`.
For an ambiguous zero-task response, the preview waits until the evidence is at
least 60 seconds old and checks the deterministic normal worker `startedBy`
identity twice. The normal ECS monitor identity is also required to be quiet,
so recovery cannot claim the run while its prior coordinator is live.

The resulting action is deterministic:

- For an unfinished run, a nonempty queue launches new workers without sending
  any messages. This safely drains Standard SQS redeliveries too.
- An empty queue sends only input IDs missing both a valid result and a valid
  permanent-failure object, then launches workers.
- Exact coverage with an empty queue launches no workers. An unfinished monitor
  manifest can be finalized; an already-completed manifest is never dispatched
  again.

Execute only after reviewing the preview:

```console
gv-dashboard-etl courts resume 2026-08-20T140430Z-0116 \
  --execute --monitor-in-ecs
```

For an attended recovery, replace `--monitor-in-ecs` with `--wait`.

Every execution creates an append-only
`runs/<run-id>/recovery-attempts/<attempt-id>/plan.json` before queue or worker
mutations. Worker and monitor task identities are written beside it. The
attempt ID also scopes distinct, deterministic ECS client tokens, so SDK retries
cannot duplicate an attempt and a later recovery cannot alias an earlier task
set.

`force_rescrape` is immutable manifest provenance. Full runs must preserve it as
`true`; a recovery cannot silently turn a forced full scrape into a cache-skipping
incremental run. Legacy sample manifests did not record whether `--force` was
used and therefore fail closed instead of guessing.

Submit and recovery decide which IDs enter SQS. Once a validated same-run
message is queued, the worker never drops it merely because the mutable global
cache or an exact-run terminal object exists. Every actual delivery performs one
portal lookup and passes through the full evidence protocol. A crash/redelivery
can therefore repeat one incident lookup, but selective recovery never reseeds
or reruns already covered incidents as a whole.

Before either result or permanent-failure compatibility object is written, the
worker appends the exact body to content-addressed `terminal-candidates/v1/`
evidence and conditionally claims the run/item's single
`terminal-decisions/v1/` envelope. That one decision prevents concurrent result
and failure writers from both becoming canonical. A losing same- or cross-kind
observation remains evidence and blocks publication until explicitly reviewed;
arrival order is never treated as a correctness policy.

After the canonical duplicate/conflict outcome is durably known, the worker
commits a MessageId/body-bound `terminal-dispositions/v1/` audit record before
deleting the main-queue message. Dispositions are deletion evidence only; they
do not authorize a no-scrape fast path. Candidate-journal, decision, canonical,
or conflict-record failures leave the message for redelivery instead of erasing
a contradictory observation. Permanent failures also retain append-only
`failure-conflicts/` evidence. A matching exact `accept-decision` review can
adjudicate that candidate; unmatched or malformed failure conflicts still block.

`terminal-decision-resolutions/v1/` is content-addressed by item, decision body,
rejected candidate body, and resolution body. Its strict record also binds the
canonical body/semantic observation, decision winner, rejected observation,
timezone-aware review time, reviewer, and nonblank rationale. Use
`write_accept_terminal_decision_resolution` only with all three expected
digests from the reviewed evidence. The earlier reviewed-canonical protocol uses
the equally privileged `result-conflict-resolutions/v1/` namespace. ECS task
roles and GitHub workflow roles must not have object mutation access to any
human-review resolution namespace: an operator/admin IAM
principal plus CloudTrail is the actual authentication boundary for the human
review; `reviewed_by` alone is not. The runtime exports
`HUMAN_REVIEW_RESOLUTION_PATHS` so IAM policy generation and audits must bind
the complete exact namespace inventory without duplicating namespace strings.

The transport is deliberately at-least-once. A true concurrent Standard SQS
duplicate can repeat one portal lookup, and a DLQ send can be duplicated if its
response is lost. This does not require rerunning the whole scrape: canonical
CAS plus the terminal-candidate journal preserve every distinct conclusion.
DLQ consumers must deduplicate using run/item/message evidence.

New submissions publish and strongly reconcile immutable `input.jsonl` first;
only then is `manifest.json` written as the run commit marker, and only after
both exact bodies are confirmed can SQS seeding begin. An input-only interrupted
submission has performed no scrape or queue mutation and retains its active-run
lease for explicit operator diagnosis; it is never treated as a clean release.

Before execution, the input is re-read with `If-Match` against the planned ETag
and its SHA-256, terminal/conflict inventory, stopped-task proof, and queue state
are revalidated. The recovery coordinator will dispatch downstream processing
only after the main queue is empty, every recovery task exits successfully,
terminal result/failure coverage is exact, and unresolved conflict count is
zero.

If a worker/monitor launch was partial or its RunTask response was ambiguous,
the recovery lease intentionally remains fenced. Reconcile it read-only first:

```console
gv-dashboard-etl courts resume-reconcile \
  2026-08-20T140430Z-0116 20260820T201500000000Z-abcd1234
```

The command checks every known task ARN plus the attempt-scoped worker and
monitor `startedBy` identities twice, including tasks whose desired status is
already `STOPPED` but whose last status is still stopping. It also requires a
stable queue, unchanged terminal/conflict inventory, and the exact retained
`recovery:<attempt-id>` lease generation. After reviewing that output, return
only that fence to the same run with append-only reconciliation evidence:

```console
gv-dashboard-etl courts resume-reconcile \
  2026-08-20T140430Z-0116 20260820T201500000000Z-abcd1234 --execute
```

Then run `resume` again; it will reuse all terminal checkpoints and choose from
the queue state observed at that time. Execution first appends a
`return-authorized` record, performs the exact lease CAS, and only then appends
a second record bound to the returned run-owner generation; an interrupted CAS
can never leave evidence falsely claiming the return completed. The handback is
not a terminal release:
even after its TTL expires, another run cannot acquire the shared queue, while a
new recovery attempt for this same run can. Manifest finalization requires a second
60-second queue quiet window after terminal inventory, atomically transfers the
lease generation to a deterministic `finalize:` owner before manifest CAS, and
refuses to dispatch an already-completed manifest. Recovery cannot claim that
finalizing owner; completed courts processing claims directly from it. If the
manifest PUT response is lost, a strongly consistent read must prove the exact
attempted body before dispatch continues. An unchanged preimage proves that the
PUT did not commit and permits returning the fence; any other unreadable or
unexpected state records `manifest-publication-ambiguous.json` and retains the
finalizing owner for operator diagnosis.

If GitHub definitively rejects downstream dispatch after the completed manifest
commits, the finalizing owner is retained and append-only evidence is written to
`dispatch-rejections/v1/`. Diagnose the rejection and confirm that no
`courts-process.yml` run already exists for this scraper run, then perform the
cheap process-only dispatch exactly once (do not rerun the scraper):

```console
gh run list --workflow courts-process.yml --branch main --limit 20
gh workflow run courts-process.yml --ref main \
  -f run_id=2026-08-20T140430Z-0116
```

The process workflow claims that exact retained finalizer before reading the
same-run objects. An unknown GitHub delivery is not manually retried until its
existing run state has been conclusively correlated.

Do not purge a queue or delete terminal/conflict evidence to make a recovery
pass. Diagnose and preserve the failed attempt; the next plan will reuse every
valid terminal object and select only genuinely missing work.

Recovery does not currently support intentionally invalidating a trusted
terminal incident for re-scraping. That requires a separately reviewed,
append-only adjudication format bound to the original object hash; do not delete
or overwrite terminal evidence as a substitute. New monitors retain terminal task snapshots as described below. For older runs
whose task details already expired, use the explicit retirement reconciliation;
an ECS `MISSING` response alone never authorizes recovery.


## Browser deadlines and durable task evidence

The courts plugin uses `SupervisedScraper`: a parent process gives each portal
operation a hard wall-clock budget while a spawned child reuses its browser.
Scrapes have 300 seconds; startup, reset, artifact capture, and close each have
30 seconds. Termination and forced termination each get two seconds. A broken
or timed-out child is fatal to its ECS worker, leaving the receipt unacknowledged
for SQS redelivery. The worker exits so container teardown also removes detached
browser descendants. The supervisor does not launch replacement ECS tasks.
Use the same-run recovery protocol after all original workers and monitors stop.

Every monitor poll persists observed `STOPPED` workers at
`runs/<run-id>/task-terminal/v1/<sha256-task-arn>.json` before using them for
completion. These immutable records retain the run/cluster/task identity,
observation time, stop details, and container exit codes without environment
variables or secrets. Subsequent polls and restarted monitors reuse them without
requiring ECS to retain the task forever. Failed or unknown exits remain failed
or unknown; they cannot authorize normal monitor completion. Recovery needs
proof the old workers stopped, then separately proves exact result coverage.

## Historical tasks whose ECS records expired

Use this only for an incomplete original run whose stopped-task observations
predate durable snapshots. Preserve the incident logs first. Stop any genuinely
stranded task through the operational change process and wait until **all**
recorded and discoverable original/recovery workers and monitors stop. The
command below does not stop anything or delete the active lease.

An operator must review retained evidence demonstrating retirement for every
missing ARN. Preserve the actual log/event excerpts with their timestamps and
exact task identities; a `MISSING` response, silence, or an expired lease is not
sufficient evidence. Record those excerpts in a UTF-8 JSON review file with:

| Field | Required value |
| --- | --- |
| `schema_version` | `1` |
| `run_id`, `cluster_arn` | Exact original run and ECS cluster |
| `input_sha256` | Original manifest's immutable input digest |
| `task_set_sha256` | SHA-256 of UTF-8 `json.dumps(sorted(read_prior_task_arns(s3, config, run_id)), separators=(",", ":"))` |
| `lease_created_at` | Exact active original run-owner generation, timezone included |
| `reviewed_at` | Actual timezone-aware review time, no older than 24 hours |
| `reviewer`, `rationale` | Actual reviewing operator and specific reasoning |
| `evidence` | Retained reviewed task/log evidence, not merely an expiring link |
| `retired_task_arns` | Exactly the ARNs that currently return explicit ECS `MISSING` |
| `conclusion` | `stopped-exit-status-unknown` |

Use the configured operator AWS identity, with the exact pinned `uv` version,
from `packages/etl`:

```console
uv run gv-dashboard-etl courts reconcile-retired-tasks RUN_ID --review-file review.json
uv run gv-dashboard-etl courts reconcile-retired-tasks RUN_ID --review-file review.json --execute
uv run gv-dashboard-etl courts resume RUN_ID
uv run gv-dashboard-etl courts resume RUN_ID --execute --monitor-in-ecs
```

The first command is read-only. Execution repeats the input/task/lease checks,
requires no live discovered workers or monitors, and requires a 60-second stable
queue with no in-flight messages before appending records under
`task-retirement-resolutions/v1/`. A changed lease, task inventory, input digest,
transport/authorization error, or conflicting review blocks it. Retrying the
same file is idempotent. Keep the file until every append has been confirmed.
The review only supplies quiescence evidence to recovery: it never invents an
exit code, certifies scraper success, or relaxes result/conflict/coverage checks.

Only an operator/admin IAM identity may mutate this new review namespace;
workers and workflow roles may read it. Deploy and audit explicit denies using
`HUMAN_REVIEW_RESOLUTION_PATHS` before enabling this path. The self-reported
reviewer field is audit metadata; IAM and CloudTrail provide the authorization
boundary. These permissions are provisioned outside this repository.

## Watchdog and rollout

`uv run gv-dashboard-etl courts health` is a read-only JSON probe of the current
run. It exits nonzero for expired unresolved leases, a failed/stale monitor,
failed/missing worker evidence, stale worker progress, a run older than 12 hours,
or an inability to verify health. New manifests require monitor/worker progress;
missing diagnostics after ten minutes fail too. Old manifests remain inspectable
without retroactively requiring the new diagnostic schema. Active runs that
finish within the polling interval may never be observed by the watchdog; their
completed lease and published metadata are the success evidence.

Monitor status is written every poll to `monitor-state/v1/`; worker progress is
written between queue deliveries at most once per minute to `worker-progress/v1/`.
The watchdog uses a ten-minute silence threshold. It runs hourly at minute 45
UTC through the Fly scheduler, so alert latency is up to the next hourly check.
It never renews a lease, stops a task, retries a dispatch, or starts a scrape.

The workflow independently checks `/meta/courts`: the last full, coverage-complete
publication must be no older than eight days and must carry the supported
publication/search/conflict contracts with no missing/extra/unresolved results.
A valid `partial` publication with explicit permanent failures is allowed; it
is not confused with incomplete coverage. Daily production smoke makes the same
check before sending `PRODUCTION_SMOKE_HEARTBEAT_URL`. Thus the existing external
dead-man check also detects stale courts, including scheduler/GitHub outages.
The hourly watchdog itself uses GitHub failure notifications; it does not send
the daily external heartbeat or silently add another alert service.

Roll out in this order:

1. Merge the workflow/probe and validate a manually dispatched
   `courts-watchdog.yml`. It should report the current incident as unhealthy.
   Verify GitHub failure notifications and the existing daily dead-man check
   reach the intended operator; an Actions red X alone is not a delivery test.
2. Audit runtime IAM: S3 get/list for these records, worker progress writes,
   monitor status/terminal writes, and explicit mutation denies for **all**
   human-review namespaces. Keep the existing lifecycle retention for recovery
   evidence. Do not give the watchdog a dispatch token or auto-recovery powers.
3. Build, scan, browser-smoke, and promote the new immutable scraper image using
   the existing Chrome release gates and separate verified worker/monitor task
   definitions. Preserve the previous digest and revisions for rollback.
   Already-running containers continue using their original code.
4. Deploy the Fly scheduler with `just fly-deploy-scheduler` through its existing
   single-Machine guard. Verify the new hourly dispatch without introducing a
   second scheduler. Workflow files alone do not activate this cadence.
5. Recover the existing run using the reviewed evidence and read-only preview.
   Reuse its valid checkpoints. If coverage is already exact and the queue is
   empty, recovery launches no workers and only finalizes/dispatches processing.
   Confirm the correlated `courts-process.yml` completes, `/meta/courts` advances
   to that run, and a subsequent shootings publication adopts the court snapshot.
   A green submission means ECS accepted tasks, not that data was published.

If downstream dispatch was ambiguous or the manifest is already complete,
follow the earlier process-only reconciliation instructions. Never bypass that
fence by deleting `active-run.json`, purging SQS, or submitting a duplicate run.
Rollback of the runtime restores the prior verified task revisions; diagnostic
and retirement records are retained. Reverting the scheduler cadence requires
redeploying the one scheduler, not creating a second schedule in GitHub.
