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

- read runtime config from environment variables injected by ECS
- rely on the ECS task role for AWS credentials
- never bake AWS keys or tokens into the image

## Runtime Environment

Inject runtime configuration through your ECS task definition or deployment
system. Common variables are:

```text
ENV=prod
AWS_ACCOUNT_ID=123456789012
AWS_REGION=us-east-1
S3_BUCKET=my-scraper-bucket
S3_SCRAPER_PREFIX=my-scraper
SQS_QUEUE_NAME=my-scraper
SQS_DLQ_NAME=my-scraper-dlq
ECS_CLUSTER_NAME=my-scraper
ECS_TASK_DEFINITION=my-scraper
ECS_CONTAINER_NAME=my-scraper
ECS_SUBNET_IDS=subnet-a,subnet-b
ECS_SECURITY_GROUP_IDS=sg-a
```

`RUN_ID` is set by the submitter when launching worker and monitor tasks.

## Build And Push To ECR

After your ECR repository exists:

```bash
ECR_URL=123456789012.dkr.ecr.us-east-1.amazonaws.com/my-scraper
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=123456789012

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin \
    "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

docker buildx build --platform=linux/amd64 -t my-scraper:latest -f Dockerfile .
docker tag my-scraper:latest "$ECR_URL:latest"
docker push "$ECR_URL:latest"
```

Point your ECS task definition at the image URI you pushed.

## Optional Just Recipes

Projects that use `just` can import reusable container and scraper CLI recipes:

```just
aws_batch_scraper_cli_dir := "etl"
aws_batch_scraper_cli := "gv-dashboard-etl"
aws_batch_scraper_cli_group := "courts"
aws_batch_scraper_dockerfile := "packages/etl/Dockerfile"
aws_batch_scraper_docker_context := "."
aws_batch_scraper_ecr_repository_name := env_var_or_default("ECR_REPOSITORY_NAME", "ujs-scraper")
aws_batch_scraper_aws_region := env_var_or_default("AWS_REGION", "us-east-1")
aws_batch_scraper_aws_account_id := env_var_or_default("AWS_ACCOUNT_ID", "")
aws_batch_scraper_aws_profile := env_var_or_default("AWS_PROFILE", "")

import "packages/aws-batch-scraper/just/aws-batch-scraper.just"
```

This adds generic recipes such as `scraper-build-container`,
`scraper-push-container`, `scraper-submit`, `scraper-monitor`, and
`scraper-bench`. Your project Justfile can wrap them with domain-specific names
such as `courts-submit` or `build-container`.

## Templates

- `examples/docker/Dockerfile.python`: pure Python or HTTP scrapers
- `examples/docker/Dockerfile.playwright`: browser scrapers using Playwright
- `examples/docker/Dockerfile.monorepo`: monorepos with local editable packages

The repository `packages/etl/Dockerfile` is the courts scraper implementation image. It
is useful as a monorepo + Playwright example, but it is not the framework image.
