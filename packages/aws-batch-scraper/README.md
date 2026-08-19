# aws-batch-scraper

`aws-batch-scraper` is a small framework for running many independent scrape
jobs on AWS:

```text
input_loader -> SQS queue -> ECS/Fargate workers -> S3 result objects
                                             -> monitor -> optional dispatch
```

It is intentionally scraper-agnostic. You provide the scraper, input list, and
container image. The framework handles queue seeding, Fargate worker launch,
worker idempotency, per-item result writes, run manifests, aggregation, and run
monitoring.

## Plugin Contract

A scraper package provides five pieces:

1. A `Scraper` implementation:

   ```python
   from aws_batch_scraper.types import ScrapeResult, ScrapeStatus, WorkItem

   class MyScraper:
       def __call__(self, item: WorkItem) -> ScrapeResult:
           return ScrapeResult(status=ScrapeStatus.SUCCESS, data={"value": item.item_id})

       def reset(self) -> None:
           pass

       def close(self) -> None:
           pass
   ```

2. Optional diagnostics:

   ```python
   def failure_artifacts(self, item: WorkItem) -> list[FailureArtifact]:
       ...
   ```

3. An input loader:

   ```python
   def load_items(config: SubmitterConfig) -> list[WorkItem]:
       return [WorkItem(item_id="item-1")]
   ```

4. Config subclasses with scraper-specific defaults.

5. A Typer CLI:

   ```python
   import typer
   from aws_batch_scraper.cli import create_cli

   app = typer.Typer()
   app.add_typer(
       create_cli(
           name="scraper",
           script_name="my-scraper",
           scraper_factory=MyScraper,
           input_loader=load_items,
           worker_config_class=MyWorkerConfig,
           submitter_config_class=MySubmitterConfig,
       ),
       name="scraper",
   )
   ```

See `examples/simple_scraper/` for a complete minimal package.

## CLI Commands

The generated CLI includes:

- `submit`: load inputs, write the immutable run manifest, seed SQS, and launch workers
- `worker`: run inside ECS/Fargate and process SQS messages
- `monitor --run-id/--latest`: verify the saved worker tasks stopped successfully,
  verify the queue drained, finalize the run, and optionally dispatch downstream work
- `monitor` without a run selector: legacy queue-depth diagnostic only; it does
  not finalize a run or release its lease
- `aggregate`: read result JSON from S3 and print status counts
- `run-stats`: print run timing and throughput
- `failures`: list permanent failures for a run
- `bench`: run a local threaded benchmark without AWS

Typical local commands:

```bash
my-scraper scraper bench --sample 20
my-scraper scraper submit --dry-run --sample 10
my-scraper scraper submit --monitor-in-ecs
my-scraper scraper aggregate
```

Choose exactly one coordinator: use `submit --monitor-in-ecs` for the normal
detached run, or `submit --wait` to coordinate synchronously. Do not also start
`monitor --latest`; that command is only for manual recovery after proving no
ECS monitor is active for the run.

## Work Message Contract

The submitter validates every item before the first SQS write. Each message is
a strict JSON object with protocol-owned fields plus optional plugin fields:

```json
{
  "item_id": "item-1",
  "run_id": "20260818T120000Z-a1b2c3",
  "force_rescrape": false,
  "plugin_field": "value"
}
```

`item_id` and `run_id` are nonblank strings, and `force_rescrape` is a strict
boolean carried on that message. A plugin cannot put `item_id`, `run_id`, or
`force_rescrape` in `WorkItem.extra`. Workers validate each message inside the
per-message exception boundary; malformed JSON, duplicate keys, nonstandard
numbers such as `NaN`, and invalid types are quarantined instead of terminating
the worker.

Use `ScrapeStatus.NO_RESULTS` only when the source explicitly and successfully
reports no result. Empty, partially parsed, blocked, or otherwise ambiguous
responses must be retryable or end as `FAILED`; they are not negative evidence.

## Result And Run Schema

Conclusive workers first write the exact-run observation, then update the
cross-run idempotency cache:

```text
s3://<bucket>/<s3_scraper_prefix>/runs/<run_id>/results/<item_id>.json
s3://<bucket>/<s3_scraper_prefix>/results/<item_id>.json
```

Permanent failures are run-scoped and never replace the global conclusive cache:

```text
s3://<bucket>/<s3_scraper_prefix>/runs/<run_id>/failures/<item_id>.json
```

Exact-run conclusive results are conditional first-writer-wins objects. A
duplicate observation may reuse the first canonical body, but a disagreement
cannot overwrite it. The worker records durable terminal evidence at
`runs/<run_id>/result-conflicts/<item_id>.json`, moves the duplicate message to
the DLQ only after that write succeeds, and exact-run aggregation and downstream
publication fail closed while any such evidence exists.

Each object validates as `ScrapeResult`:

- `status`: `SUCCESS`, `NO_RESULTS`, `FAILED`, or `INVALID_INPUT`
- `data`: scraper-specific JSON data
- `classification`, `subreason`, `error_message`: diagnostic fields
- `is_soft_blocked`, `is_network_error`: retry hints used by the worker
- `item_id`, `run_id`, `scraped_at`, `scrape_duration_s`: worker metadata
- `extra`: additional scraper-specific diagnostics

The stable global result is only an optimization for future submission. Exact
run aggregation must use `runs/<run_id>/input.jsonl`, the matching manifest,
and only that run's result/failure prefixes. Processing must require a valid
`completed_at` in the manifest and an input count matching `input_size`; this
prevents stale global data or an early manual dispatch from masquerading as the
current run.

## Lease And Monitor Contract

Each scraper prefix has one conditional S3 lease at `active-run.json`. It stores
the run/owner identity and timezone-aware `created_at`/`expires_at` timestamps.
Acquisition, renewal, owner transfer, and release use ETag compare-and-swap.
The TTL is a liveness alarm, not proof that ECS tasks stopped or shared queues
were reconciled, so natural expiry never authorizes automatic cross-run
takeover. A new run can replace an expired object only when matching completed
terminal evidence proves that exact lease generation was explicitly released.
Missing, invalid, mismatched, or provisional evidence fails closed and requires
an operator to reconcile ECS tasks plus visible, in-flight, and delayed queue
states before explicitly releasing the exact owner. Terminal releases preserve
evidence at `runs/<run_id>/lease-terminal.json`; a caller that no longer owns
the exact lease cannot release it.

Downstream processing should first prove the exact run manifest is complete,
then atomically claim the lease under a unique processing owner. Renewal under
the original run owner is not an exclusive processing claim: two duplicate
callers could otherwise both renew it. Only the successful claimant may publish
and write the terminal release record. A manifest-complete run may CAS-claim its
own expired coordinator lease because its monitor already proved the tasks and
queues terminal. Retrying an expired processing owner additionally requires a
matching completed `failure` terminal record; a successful processing release
cannot be retried.

A run-scoped monitor requires a nonempty `tasks.json`, describes every saved
task ARN, waits for every task to reach `STOPPED`, requires a successful exit
code from each essential container, and then requires visible, in-flight, and
delayed queue counts all to be zero. Those terminal counts are persisted in the
completed manifest. Missing/corrupt task metadata, omitted ECS tasks, nonzero
or missing exit codes, and AWS access/transport errors fail closed. Queue depth
alone is not proof that worker tasks have exited.

The submitter writes the manifest before the first queue mutation. A partial or
unknown manifest/seed, any seeded run with zero confirmed workers, or an
ambiguous/partial ECS launch retains the active lease and writes
`submission-recovery.json`. Ambiguous GitHub dispatch and terminal queue proof
have their own run-scoped recovery records. This intentionally blocks overlap
until an operator reconciles the external state and explicitly completes the
matching release protocol; elapsed TTL alone never clears the block or converts
an unknown side effect into a clean failure/retry.

The downstream workflow POST is non-idempotent. Only an explicit HTTP 429 is
retried; timeouts, connection loss, 5xx responses, and undocumented success
responses raise `WorkflowDispatchDeliveryUnknownError` immediately. The monitor
persists ambiguity evidence and retains the lease so an operator can inspect
GitHub Actions before deciding whether a manual dispatch is safe.

## AWS Runtime

The framework expects these runtime values from environment variables or config
subclass defaults:

- `AWS_ACCOUNT_ID`, `AWS_REGION`
- `S3_BUCKET`, `S3_SCRAPER_PREFIX`
- `SQS_QUEUE_NAME`, `SQS_DLQ_NAME`
- `ECS_CLUSTER_NAME`, `ECS_CONTAINER_NAME`
- `ECS_TASK_DEFINITION`, the worker definition, and
  `ECS_MONITOR_TASK_DEFINITION`, the monitor definition. Both must be exact
  `family:revision` values or full revisioned task-definition ARNs. They must
  identify different revisions; bare families and a shared definition are
  rejected before any ECS launch.
- `ECS_SUBNET_IDS`, `ECS_SECURITY_GROUP_IDS`; both must be explicit, nonempty,
  unique ID lists (the default security group is never selected implicitly)
- `RUN_ID`, set by the submitter for worker and monitor tasks
- `GITHUB_REPOSITORY`, `GITHUB_WORKFLOW_FILE`, and `GITHUB_DISPATCH_TOKEN` when
  completed runs must dispatch a GitHub Actions workflow with the exact
  `run_id` input. `GITHUB_WORKFLOW_FILE` is a filename such as
  `courts-process.yml`, not a path. Missing dispatch config is a terminal error;
  tests/local tools can opt out only through explicit injection.

Before the first durable submission write, the framework resolves both task
definitions through ECS and requires the exact ACTIVE cluster, ACTIVE Fargate
definitions, the configured container in each, no task-definition entry-point
override, the image's default worker command, digest-pinned images, the same
primary image digest, no dispatch token anywhere in the worker definition, and
a monitor token supplied through the primary container's ECS `secrets` list
rather than plaintext. Both launch helpers repeat this preflight. The submitter
identity therefore needs `ecs:DescribeTaskDefinition`; AWS requires that action
with `Resource: "*"`, so do not attach a cluster-resource condition to it.

Provision those AWS resources with your current infrastructure workflow. The
framework only needs the runtime values above and AWS credentials from the
default boto3 credential chain. See:

- `docs/quickstart.md`
- `docs/container.md`

## Container Contract

There is no required public base image. Scraper dependencies vary too much for
one image to be correct for everyone. Instead, your image must:

- install your scraper package and `aws-batch-scraper`
- expose your CLI entry point
- default to the worker command, for example `my-scraper scraper worker`
- accept monitor command overrides, for example
  `my-scraper scraper monitor --run-id <run_id>`
- rely on ECS task roles for AWS credentials
- run an immutable image selected by digest (`repository@sha256:...`), not a
  mutable `latest` tag

Dockerfile templates live in `examples/docker/`.

## Least-Privilege IAM

Scope all permissions to the configured queue, DLQ, bucket prefix, cluster, and
two task definitions. Split submitter, worker, and monitor IAM identities when
your deployment can support separate roles:

- submitter: `sqs:SendMessage`, queue attribute reads; S3 list/read of the
  global result cache plus get/put of run manifests, task metadata, ambiguity
  evidence, and the active lease; `ecs:DescribeTaskDefinition`, `ecs:RunTask`,
  and the narrowly scoped `iam:PassRole` permissions required by both task
  definitions
- worker: receive/delete/change visibility and queue-attribute reads on the main
  queue, `sqs:SendMessage` on the DLQ, and S3 head/put only for global results
  and its exact run's results, failures, artifacts, and logs
- monitor: `ecs:DescribeTasks`; queue/DLQ attribute reads; and S3 get/conditional
  put for the run manifest, `tasks.json`, lease, and terminal/ambiguity evidence

The task execution role should contain image-pull/logging permissions. When the
monitor task definition injects `GITHUB_DISPATCH_TOKEN` or another ECS secret,
its execution role also needs least-privilege `secretsmanager:GetSecretValue`
or `ssm:GetParameters` for that exact secret plus `kms:Decrypt` for its CMK when
applicable. The application task role carries the runtime SQS/S3/ECS permissions
above. A shared worker and monitor task definition would expose monitor-only
secrets to workers, so the configuration rejects one revision in both roles.
The worker definition must not reference the dispatch-token secret. A distinct
worker execution role that cannot read that secret is the preferred further
least-privilege boundary. Keep the token repository-scoped, short-lived, and
minimally permissioned: a fine-grained token needs repository **Actions: read
and write**, not **Contents: write**, to create the workflow dispatch. GitHub
Actions should use an OIDC role with
`contents: read` and `id-token: write`, not long-lived AWS keys.

Before changing task definitions to this protocol, stop old tasks and drain
visible, in-flight, and delayed queue messages. Then register a revision with
the immutable image digest for each role. Set `ECS_TASK_DEFINITION` to the exact
worker revision and `ECS_MONITOR_TASK_DEFINITION` to a different exact monitor
revision. Verify that only the monitor definition references the dispatch token,
then verify a sampled run writes run-scoped objects before restoring production
scheduling. Do not mix workers that only write global results with processors
that require exact-run results.
