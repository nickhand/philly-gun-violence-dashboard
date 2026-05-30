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
- ECS task definition that runs the scraper container
- ECS task role and execution role
- SQS queue and dead-letter queue
- S3 bucket name
- VPC subnet IDs
- security group IDs

The task definition should inject the runtime environment variables documented
in `docs/container.md` and use the worker command for the container.

## 3. Build And Push The Container

Choose a Dockerfile template from `examples/docker/`.

```bash
ECR_URL=123456789012.dkr.ecr.us-east-1.amazonaws.com/simple-scraper
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=123456789012

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin \
    "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

docker buildx build --platform=linux/amd64 -t simple-scraper:latest -f Dockerfile .
docker tag simple-scraper:latest "$ECR_URL:latest"
docker push "$ECR_URL:latest"
```

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
export ECS_TASK_DEFINITION=my-scraper
export ECS_CONTAINER_NAME=my-scraper
export ECS_SUBNET_IDS=subnet-a,subnet-b
export ECS_SECURITY_GROUP_IDS=sg-a
```

## 5. Submit And Monitor

```bash
simple-scraper scraper submit --monitor-in-ecs
simple-scraper scraper monitor --latest
simple-scraper scraper aggregate
```

Use `--sample N` while testing and `--force` when you want to ignore existing
result objects.
