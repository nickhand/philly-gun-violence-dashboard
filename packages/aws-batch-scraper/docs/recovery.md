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
- a previously recorded worker task is missing or is not `STOPPED`;
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
digests from the reviewed evidence. Workers must not have `s3:PutObject` access
to this prefix: an operator/admin IAM principal plus CloudTrail is the actual
authentication boundary for the human review; `reviewed_by` alone is not.

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
or overwrite terminal evidence as a substitute. Also perform the first recovery
while ECS can still describe recorded stopped tasks (AWS retains stopped task
details for a limited period); durable terminal task snapshots are a follow-up
for arbitrarily old runs.
