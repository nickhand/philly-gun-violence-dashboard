# Quickstart

This guide builds a tiny scraper, points it at existing AWS resources, pushes a
container to ECR, and submits a run.

## 1. Create A Scraper CLI

Use `examples/simple_scraper` as the shape:

```python
import typer
from aws_batch_scraper.cli import create_cli

app = typer.Typer()
app.add_typer(
    create_cli(
        name="scraper",
        script_name="simple-scraper",
        scraper_factory=SimpleScraper,
        input_loader=load_items,
        worker_config_class=SimpleWorkerConfig,
        submitter_config_class=SimpleSubmitterConfig,
    ),
    name="scraper",
)
```

Run locally:

```bash
simple-scraper scraper bench --sample 5
simple-scraper scraper submit --dry-run --sample 5
```

## 2. Prepare AWS Resources

Create or identify these AWS resources with your current infrastructure
workflow:

- ECR repository
- ECS/Fargate cluster
- Separate ECS worker and monitor task definitions that run the same immutable
  scraper image
- ECS task and execution roles; separate worker/monitor roles are recommended
  as a further least-privilege boundary
- SQS queue and dead-letter queue
- S3 bucket name
- VPC subnet IDs
- security group IDs

The worker definition should use the worker command and must not inject the
GitHub dispatch token. The monitor definition accepts the monitor command
override and is the only definition permitted to inject that secret. The
submitter supplies nonsecret runtime settings as ECS overrides; the monitor
does not need to hard-code a reference to its own revision. See
`docs/container.md` for the complete runtime contract.

## 3. Build And Push The Container

Choose a Dockerfile template from `examples/docker/`.

```bash
export AWS_ACCOUNT_ID=123456789012
export AWS_REGION=us-east-1
export ECR_REPOSITORY_NAME=simple-scraper
export SCRAPER_IMAGE_TAG="$(git rev-parse HEAD)"
just scraper-build-and-push-container
```

Register separate worker and monitor ECS task definitions with the digest URI
printed by the recipe, not a mutable `:latest` tag. This makes the
worker/message/result protocol used by each run auditable and prevents a task
launch from silently resolving an older image. Save both exact registered
`family:revision` values (or full revisioned ARNs); the framework rejects a bare
family or one revision configured for both roles.

Make ECR tag immutability and scan-on-push external prerequisites. The reusable
`just` recipe performs the clean-tree, full-SHA, exact-account/repository,
absent-tag, image-label, digest, and scan checks and prints the only approved
digest URI. Do not substitute a manual `docker push` that bypasses these gates.

The submitter preflight requires `ecs:DescribeTaskDefinition` before it writes a
manifest or seeds SQS. Grant that action separately with `Resource: "*"`; unlike
`ecs:RunTask`, it must not carry an `ecs:cluster` resource condition.

## 4. Configure Local Submitter Environment

Set values from your AWS resources:

```bash
export ENV=prod
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=123456789012
export S3_BUCKET=my-scraper-bucket
export S3_SCRAPER_PREFIX=my-scraper
export SQS_QUEUE_NAME=my-scraper
export SQS_DLQ_NAME=my-scraper-dlq
export ECS_CLUSTER_NAME=my-scraper
export ECS_TASK_DEFINITION=my-scraper:42
export ECS_MONITOR_TASK_DEFINITION=my-scraper-monitor:17
export ECS_CONTAINER_NAME=my-scraper
export ECS_SUBNET_IDS=subnet-a,subnet-b
export ECS_SECURITY_GROUP_IDS=sg-a
export GITHUB_REPOSITORY=owner/repository
export GITHUB_WORKFLOW_FILE=process-results.yml
```

Do not export `GITHUB_DISPATCH_TOKEN` here. Inject it only through the monitor
task definition's ECS `secrets` list. Give that repository-scoped fine-grained
token **Actions: read and write** only; it does not need **Contents: write**.

## 5. Submit And Monitor

```bash
simple-scraper scraper submit --monitor-in-ecs
simple-scraper scraper aggregate
```

Use one terminal coordinator per run: either `submit --monitor-in-ecs` (normal)
or `submit --wait` (synchronous). Use `monitor --latest` only for manual
recovery after proving that no ECS monitor is still active for that run; running
both can duplicate finalization and downstream dispatch.

Use `--sample N` while testing and `--force` when you want to ignore existing
result objects.
