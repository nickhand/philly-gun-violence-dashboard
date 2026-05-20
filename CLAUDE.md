# UJS Scraper — Architecture Guide

Queue-based SQS scraper for the PA Unified Judicial System portal.
AOPC sign-off received for off-hours scraping; design is optimized
for politeness, not evasion.

## Why This Architecture

The original design used static partitioning (50 shards, 50 Fargate tasks).
Two real problems at scale:

1. **Static partitioning produces stragglers.** A task with a bad block streak
   holds up the whole run while others sit idle. There is no work-stealing.
2. **50-way parallelism was the actual cause of blocks.** More concurrent Fargate
   IPs makes the pattern more obvious to the portal, not less. Splitting work
   doesn't lower per-IP request rate in a way that helps.

The queue-based design fixes both: idle workers grab the next message
automatically; worker count is an independent knob (default: 2).

AOPC has explicitly authorized off-hours bulk access for this public-interest
project. The scraper no longer needs to evade detection — the goal is to be
a polite, predictable batch consumer that runs overnight on weekends.

## Target Architecture

Three independent stages, no coupling between them. SQS is the orchestrator.

- **Submit.** One-shot script: filter out already-scraped incidents → seed SQS
  queue → write run manifest to S3 → exit. Does not wait for completion.
- **Process.** Fargate task: long-poll SQS → check idempotency → scrape →
  write result → delete message. Loops until queue drains or SIGTERM.
- **Aggregate.** Separate, optional. Reads `results/*.json` via DuckDB or
  produces a Parquet snapshot on demand. Not part of submit or process.
- **Monitor.** Polls SQS queue depth to detect completion. Writes final
  summary (completed_at, runtime, DLQ depth) to the run manifest.
- **Replay.** Small utility to move DLQ messages back to main queue after
  fixing whatever caused permanent failures.

Each stage can be re-run independently. The submitter does not block. The
aggregator does not wait for anything. **SQS carries the state; scripts are
stateless clients.**

## What to Change in Existing Code

The existing scraper logic (Playwright session, form submission, result
parsing) stays largely intact. The wrapping changes.

**In the existing loader/submitter:**

- Filter out incidents that already have results in `results/` before seeding.
- `send_message_batch` incident numbers to SQS in batches of 10.
- Write a run manifest to `runs/{run_id}/manifest.json` capturing run ID,
  timestamp, input size, queue URL, worker count.
- Persist the input list to `runs/{run_id}/input.jsonl` for reproducibility.
- Exit after seeding — do not wait for workers.

**In the existing worker/container:**

- Replace "load my chunk from S3" with an SQS `receive_message` loop using
  long polling (`WaitTimeSeconds=20`, `MaxNumberOfMessages=1`).
- Add an idempotency check (`head_object` on the result key) before scraping.
  Skip if the result already exists.
- After each scrape (any outcome), sleep `random.uniform(1.0, 2.5)` seconds.
- Add a SIGTERM handler that sets a shutdown flag and lets the current scrape
  finish.
- Exit when 3 consecutive empty polls confirm the queue is truly empty
  (visible + in-flight == 0).
- Write a stats file to `runs/{run_id}/logs/{task_id}-stats.json` on exit.

**In the existing scraper module:**

- SOFT_BLOCKED classification: allow at most 1 in-task retry, then raise
  `SoftBlocked` to the worker loop. No exponential backoff, no circuit breaker.
- Other retryable errors (timeouts, transient failures): retry up to `max_attempts`.
- No adaptive rate limiting. No staggered start. No playwright-stealth.

## S3 Layout

```
s3://{bucket}/
├── runs/{run_id}/
│   ├── manifest.json       # written at submit time; finalized by monitor
│   ├── input.jsonl         # incidents queued in this run
│   ├── logs/{task_id}-stats.json
│   └── failures/{incident}.json
└── results/{incident}.json
```

- `results/` is the **content store**, keyed by incident number, never by
  run. Re-scraping overwrites the same key. Enable S3 versioning here.
- `runs/{run_id}/` is the **audit trail**, scoped per execution. `run_id`
  format: `{ISO timestamp}-{short uuid}`.
- Each result file includes `incident_number`, `scraped_at`, and `run_id`
  so files are self-describing without their path.

## SQS Configuration

| Setting | Value | Reason |
|---|---|---|
| `VisibilityTimeout` | 600s | Longer than worst-case Playwright run |
| `MessageRetentionPeriod` | 14 days | Standard |
| `ReceiveMessageWaitTimeSeconds` | 20 | Long polling |
| `maxReceiveCount` (redrive → DLQ) | 8 | SOFT_BLOCKED requeues consume receives |

`maxReceiveCount=8` looks high but is deliberate. Every `change_message_visibility`
call counts as a receive. A low count (3–5) will DLQ messages just for hitting
a block streak.

## Failure Handling

Three tiers. The worker loop classifies; SQS does the mechanics.

**1. SOFT_BLOCKED.** Portal is temporarily blocking the worker's IP. The scraper
tries once, retries once, then raises `SoftBlocked`. The worker calls
`change_message_visibility` with a random 5–15 minute delay and immediately
polls for the next message. No in-worker sleep. A different worker IP may
pick it up sooner.

**2. Permanent failure** (parse error, malformed input, page structure changed).
Explicit `send_message` to DLQ, then `delete_message` from main. Don't waste
retries. Snapshot the error to `runs/{run_id}/failures/{incident}.json`.

**3. Transient** (network blip, OOM, Playwright crash). Do nothing. Let the
visibility timeout expire; SQS redelivers; the redrive policy DLQs after
`maxReceiveCount`. Cleanest possible handling — the queue does the work.

## Idempotency

Belt-and-suspenders approach:

1. **Submitter** filters out incidents with existing `results/` keys before
   seeding the queue (avoids queuing already-done work).
2. **Worker** calls `head_object` on the result key before scraping (catches
   races and repeated submitter runs).

If two workers race on the same incident, both scrape and write. Writes are
atomic and the content is identical — duplicate work is harmless.

## IAM Model

Three principals, three policies, no shared credentials.

- **Local user** (e.g. `nick-philly-gv-dashboard`): submitter, monitor,
  replay, aggregate. Access keys stored as a named profile (`AWS_PROFILE`).
  Permissions: SQS read+write on both queues, S3 read+write on bucket,
  ECS `run_task` on cluster.
- **Task role** (e.g. `ujs-scraper-worker`): assumed by Fargate containers
  automatically via the metadata endpoint. No long-lived credentials.
  Permissions: SQS receive/delete/change-visibility on main queue, send on
  DLQ, S3 get/put on `results/*` and put on `runs/*/logs/*`.
- **Execution role** (e.g. `ujs-scraper-execution`): used by ECS to pull
  images and write CloudWatch logs. AWS-managed
  `AmazonECSTaskExecutionRolePolicy` is sufficient.

## ECR

- Base image: `mcr.microsoft.com/playwright/python:v{X}-jammy`. Do not
  install Playwright/Chromium in a custom Dockerfile — version coupling
  between the Python package and the browser binary is fragile.
- Tag every push with `:latest` and `:${GIT_SHA}` for rollback.
- Lifecycle policy: untagged images expire after 14 days; keep only 20 most
  recent tagged.

## Operational Knobs

Default: 2 Fargate workers, overnight weekly schedule. In rough order of
impact if block rate climbs:

1. Reduce to 1 worker (`ECS_TASK_COUNT=1`). Fewer distinct IPs is the
   primary lever.
2. Widen inter-incident jitter (change `random.uniform(1.0, 2.5)` bounds
   in `scrape.py`).
3. Recycle Playwright contexts more aggressively (lower the 50-incident
   threshold in `run_worker`).
4. Contact AOPC to clarify access agreement or request rate limit increase.

## Design Decisions Worth Preserving

**Decoupled stages.** Submitter does not wait for workers. Aggregator is
independent. Resist adding "wait for completion" coordination — monitor
the queue instead.

**Content vs audit separation in S3.** Don't put run IDs in result keys.
Don't put result content in run directories. The split is what makes reruns
trivial.

**One incident per SQS message.** Don't batch incidents per message.
Visibility semantics are per-message; batching defeats independent retry.

**`change_message_visibility` for SOFT_BLOCKED, not delete-and-resend.**
Delete-and-send introduces a window where the message exists in neither
queue. `change_message_visibility` is atomic.

**Per-incident JSON files, not a single aggregated file.** Concurrent writes
don't contend. `head_object` makes idempotency trivial. DuckDB queries the
prefix directly.

**Three retry tiers, not one.** SOFT_BLOCKED, permanent failure, and
transient errors each need a different response.

## Things Not to Do

- Don't reintroduce static partitioning. Queue-based is strictly better.
- Don't scale past 5 Fargate workers without checking with AOPC. More
  concurrent IPs increases request rate in a way that may violate the
  access agreement.
- Don't run during business hours (9 AM – 5 PM ET) per AOPC agreement.
  Scheduling and triggers are managed by the GitHub Actions workflow.
- Don't store anything sensitive in SQS message bodies. Incident numbers
  are public records.
- Don't run anything under the AWS root account.
- Don't install Playwright in a custom Dockerfile.
- Don't write to `results/` from anywhere except the worker. For one-off
  backfills, write to a separate prefix and merge deliberately.
- Don't couple submit and aggregate. They are independent verbs.
