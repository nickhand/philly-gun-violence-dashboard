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
- One reviewed ECS task role and one reviewed execution role shared by these
  two definitions. Supporting separate worker/monitor roles requires distinct
  expected-role settings and is a future hardening change, not part of the
  current runtime contract.
- SQS queue and dead-letter queue
- S3 bucket name
- VPC subnet IDs
- security group IDs

The worker definition should use the worker command and must not inject the
GitHub dispatch token. Set the monitor definition's static command to exactly
`["/bin/false"]`; the framework replaces it with the monitor command only for
reviewed launches. A direct no-override launch therefore exits instead of
starting the browser with the token. The monitor definition is the only one
permitted to inject that secret. The
submitter supplies nonsecret runtime settings as ECS overrides; the monitor
does not need to hard-code a reference to its own revision. See
`docs/container.md` for the complete runtime contract.

Both definitions must use `awsvpc`, target `LINUX/X86_64`, contain only the
configured `ECS_CONTAINER_NAME`, run that container as the image's `app` user
with a read-only root filesystem, and mount one ephemeral writable volume only
at `/tmp`. They must drop `ALL` Linux capabilities and must not add
capabilities, privilege, extra mounts or containers, or kernel overrides. The
worker definition must have empty `secrets`, `environment`, and
`environmentFiles`; reviewed nonsecret settings are supplied only as per-run
overrides. Neither definition may use `repositoryCredentials`,
`credentialSpecs`, a FireLens log router, static labels, a health-check command,
exposed ports, or interactive terminals; logging, when configured, must use
`awslogs` with no `secretOptions`.

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
export ECS_EXPECTED_IMAGE_URI=123456789012.dkr.ecr.us-east-1.amazonaws.com/simple-scraper@sha256:<64-lowercase-hex>
export ECS_EXPECTED_TASK_ROLE_ARN=arn:aws:iam::123456789012:role/simple-scraper-task
export ECS_EXPECTED_EXECUTION_ROLE_ARN=arn:aws:iam::123456789012:role/simple-scraper-execution
export ECS_EXPECTED_MONITOR_SECRET_ARN=arn:aws:secretsmanager:us-east-1:123456789012:secret:simple-scraper/github-dispatch-token-AbCdEf
export ECS_PLATFORM_VERSION=1.4.0
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
