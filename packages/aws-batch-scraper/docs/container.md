# Container Contract

`aws-batch-scraper` does not require a public base image. Scrapers have very
different runtime needs, so the stable interface is a container contract plus
copyable Dockerfile templates.

## Required Behavior

Your container image must:

- install your scraper package and `aws-batch-scraper`
- expose the CLI you built with `create_cli(...)`
- default to the worker command, for example:

  ```dockerfile
  CMD ["my-scraper", "scraper", "worker"]
  ```

- support the monitor command as an ECS command override:

  ```bash
  my-scraper scraper monitor --run-id <run_id>
  ```

  The framework invokes this installed console script directly. `uv` is a
  build/development tool and is not part of the runtime container contract.

- read runtime config from environment variables injected by ECS
- rely on the ECS task role for AWS credentials
- never bake AWS keys or tokens into the image

The worker and monitor task definitions must explicitly declare a non-root
runtime user and `readonlyRootFilesystem: true`; submitter preflight rejects
either omission. Keep installed code owned by the image build user and mount an
explicit writable temporary volume for the paths required by the scraper.
Browser containers commonly need `/tmp`; route `HOME`, `TMPDIR`, and XDG
cache/config state to that mount and test the image before registration. For a
non-root Fargate task, declare that exact path with a Dockerfile `VOLUME` after
setting its intended ownership and permissions; otherwise an empty bind mount
defaults to root ownership and may not be writable by the runtime user.

## Runtime Environment

Provide runtime configuration to the submitter through its environment or
deployment system. It passes nonsecret values into worker and monitor tasks as
ECS overrides, so the monitor definition does not need to hard-code its own
revision. Common variables are:

```text
ENV=prod
AWS_ACCOUNT_ID=123456789012
AWS_REGION=us-east-1
S3_BUCKET=my-scraper-bucket
S3_SCRAPER_PREFIX=my-scraper
SQS_QUEUE_NAME=my-scraper
SQS_DLQ_NAME=my-scraper-dlq
ECS_CLUSTER_NAME=my-scraper
ECS_TASK_DEFINITION=my-scraper:42
ECS_MONITOR_TASK_DEFINITION=my-scraper-monitor:17
ECS_CONTAINER_NAME=my-scraper
ECS_SUBNET_IDS=subnet-a,subnet-b
ECS_SECURITY_GROUP_IDS=sg-a
GITHUB_REPOSITORY=owner/repository
GITHUB_WORKFLOW_FILE=process-results.yml
```

`RUN_ID` is set by the submitter when launching worker and monitor tasks.
Keep `GITHUB_DISPATCH_TOKEN` out of this environment and only in the monitor
definition's ECS `secrets` list. Use a repository-scoped fine-grained token
with **Actions: read and write**; workflow dispatch does not require
**Contents: write**.

## Build And Push To ECR

After your ECR repository exists:

```bash
export AWS_ACCOUNT_ID=123456789012
export AWS_REGION=us-east-1
export ECR_REPOSITORY_NAME=my-scraper
export SCRAPER_IMAGE_TAG="$(git rev-parse HEAD)"
just scraper-build-and-push-container
```

Before the push, configure the ECR repository with immutable tags and automatic
scanning. Tag immutability is an external release gate: the local absence check
cannot eliminate a race with another publisher. The guarded recipe binds every
inspection and scan to `AWS_ACCOUNT_ID`, verifies the returned repository URI,
requires scan-on-push, and makes up to 180 scan checks spaced 10 seconds apart
(about 30 minutes of wait time, plus AWS CLI request time). It prints the complete
`repository@sha256:...` URI only after the exact pushed image has no Critical or
High findings. Terminal, malformed, unauthorized, and timeout outcomes exit
nonzero without printing a URI. Do not replace it with an unguarded manual
`docker push` sequence.

Register separate worker and monitor ECS task-definition revisions using the
printed digest URI. Do not point either definition at `:latest`: a mutable tag
cannot prove which worker protocol a run used. Each task definition must still
use `repository@sha256:...` even when ECR tag immutability is enabled.

Set `ECS_TASK_DEFINITION` to the exact worker `family:revision` (or full
revisioned ARN) and `ECS_MONITOR_TASK_DEFINITION` to a different exact monitor
revision. Bare family names and a shared worker/monitor revision are rejected at
configuration and launch boundaries. Only the monitor definition may inject
`GITHUB_DISPATCH_TOKEN`. Prefer a separate worker execution role that cannot
read that secret.

The submitter resolves both definitions before the first durable mutation and
again at each launch boundary. It requires ACTIVE Fargate definitions, the
configured container name in both, digest-pinned images with the same primary
digest, no dispatch token in any worker container, and the monitor token in the
primary monitor container's ECS `secrets` list (never plaintext environment).
The submitter role needs `ecs:DescribeTaskDefinition` with `Resource: "*"` in a
statement without the `ecs:cluster` condition used to scope `ecs:RunTask`.

## Just Recipes

Projects that use `just` can import reusable container and scraper CLI recipes:

```just
aws_batch_scraper_cli_dir := "etl"
aws_batch_scraper_cli := "gv-dashboard-etl"
aws_batch_scraper_cli_group := "courts"
aws_batch_scraper_dockerfile := "packages/etl/Dockerfile"
aws_batch_scraper_docker_context := "."

import "packages/aws-batch-scraper/just/aws-batch-scraper.just"
```

The release recipes read `AWS_ACCOUNT_ID`, `AWS_REGION`,
`ECR_REPOSITORY_NAME`, `SCRAPER_IMAGE_TAG`, and optional `AWS_PROFILE`
directly from the environment. This keeps untrusted environment text out of
Just's generated shell source.

This adds generic recipes such as `scraper-build-container`,
`scraper-push-container`, `scraper-submit`, `scraper-monitor`, and
`scraper-bench`. Your project Justfile can wrap them with domain-specific names
such as `courts-submit` or `build-container`.

The build and push recipes require a completely clean checkout and
`SCRAPER_IMAGE_TAG` equal to the full current commit SHA. They reject an ECR tag
that already exists, label and re-check the local image revision, resolve the
exact pushed digest, make up to 180 scan checks spaced 10 seconds apart (about
30 minutes of wait time, plus AWS CLI request time), and fail on any Critical or
High finding. After those checks pass, the recipe prints the full digest URI to
use in the ECS task definition. The repository must separately
enforce immutable ECR tags and scan-on-push:

```bash
SCRAPER_IMAGE_TAG=$(git rev-parse HEAD) just scraper-build-and-push-container
```

## Templates

- `examples/docker/Dockerfile.python`: pure Python or HTTP scrapers
- `examples/docker/Dockerfile.playwright`: browser scrapers using Playwright
- `examples/docker/Dockerfile.monorepo`: monorepos with local editable packages

The repository `packages/etl/Dockerfile` is the courts scraper implementation image. It
is useful as a monorepo + Playwright example, but it is not the framework image.
