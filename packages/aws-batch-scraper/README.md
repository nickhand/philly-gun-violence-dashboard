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

- `submit`: load inputs, seed SQS, write a run manifest, and launch workers
- `worker`: run inside ECS/Fargate and process SQS messages
- `monitor`: wait for worker tasks or queue depth to finish
- `aggregate`: read result JSON from S3 and print status counts
- `run-stats`: print run timing and throughput
- `failures`: list permanent failures for a run
- `bench`: run a local threaded benchmark without AWS

Typical local commands:

```bash
my-scraper scraper bench --sample 20
my-scraper scraper submit --dry-run --sample 10
my-scraper scraper submit --monitor-in-ecs
my-scraper scraper monitor --latest
my-scraper scraper aggregate
```

## Result Schema

Workers write one JSON object per item under:

```text
s3://<bucket>/<s3_scraper_prefix>/results/<item_id>.json
```

Each object validates as `ScrapeResult`:

- `status`: `SUCCESS`, `NO_RESULTS`, `FAILED`, or `INVALID_INPUT`
- `data`: scraper-specific JSON data
- `classification`, `subreason`, `error_message`: diagnostic fields
- `is_soft_blocked`, `is_network_error`: retry hints used by the worker
- `item_id`, `run_id`, `scraped_at`, `scrape_duration_s`: worker metadata
- `extra`: additional scraper-specific diagnostics

## AWS Runtime

The framework expects these runtime values from environment variables or config
subclass defaults:

- `AWS_ACCOUNT_ID`, `AWS_REGION`
- `S3_BUCKET`, `S3_SCRAPER_PREFIX`
- `SQS_QUEUE_NAME`, `SQS_DLQ_NAME`
- `ECS_CLUSTER_NAME`, `ECS_TASK_DEFINITION`, `ECS_CONTAINER_NAME`
- `ECS_SUBNET_IDS`, `ECS_SECURITY_GROUP_IDS`
- `RUN_ID`, set by the submitter for worker and monitor tasks

Use the Terraform module in `terraform/modules/batch-scraper` to provision the
AWS pieces. See:

- `docs/quickstart.md`
- `docs/terraform.md`
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

Dockerfile templates live in `examples/docker/`.
