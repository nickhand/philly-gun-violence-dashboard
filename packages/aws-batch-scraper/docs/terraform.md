# Terraform Module

The reusable module lives at `terraform/modules/batch-scraper`. It provisions
the AWS runtime used by `aws-batch-scraper`.

See `examples/terraform/basic` for a complete minimal module call with GitHub
OIDC disabled.

## Resources Created

- SQS queue and dead-letter queue
- ECR repository
- ECS/Fargate cluster
- ECS task definition
- CloudWatch log group
- ECS task role and execution role
- optional GitHub Actions OIDC role

Networking is caller-owned in v1. Pass subnet IDs and security group IDs that
allow the task to reach the internet or your target service.

## Minimal Usage

```hcl
module "scraper" {
  source = "../../terraform/modules/batch-scraper"

  name                   = "my-scraper"
  s3_bucket              = "my-scraper-bucket"
  s3_prefix              = "my-scraper"
  queue_name             = "my-scraper"
  dlq_name               = "my-scraper-dlq"
  vpc_subnet_ids         = ["subnet-..."]
  vpc_security_group_ids = ["sg-..."]

  container_command = ["my-scraper", "scraper", "worker"]

  environment = {
    ENV                    = "prod"
    AWS_ACCOUNT_ID         = "123456789012"
    AWS_REGION             = "us-east-1"
    S3_BUCKET              = "my-scraper-bucket"
    S3_SCRAPER_PREFIX      = "my-scraper"
    SQS_QUEUE_NAME         = "my-scraper"
    SQS_DLQ_NAME           = "my-scraper-dlq"
    ECS_CLUSTER_NAME       = "my-scraper"
    ECS_TASK_DEFINITION    = "my-scraper"
    ECS_CONTAINER_NAME     = "my-scraper"
    ECS_SUBNET_IDS         = "subnet-..."
    ECS_SECURITY_GROUP_IDS = "sg-..."
  }
}
```

If `image_uri` is omitted, the task definition uses the module-created ECR
repository with the `latest` tag.

## Secrets

Pass existing Secrets Manager or SSM parameter ARNs as a map:

```hcl
secrets = {
  GITHUB_DISPATCH_TOKEN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:..."
}
```

The ECS execution role is granted permission to read those ARNs. If a secret is
encrypted with a customer-managed KMS key, grant decrypt permission separately.

## Optional GitHub OIDC

Set `github_repository = "owner/repo"` to create a GitHub Actions role that can
push images, register task definitions, seed SQS, and launch ECS tasks.

Leave `github_repository = null` to skip all GitHub-specific resources.

If your AWS account does not already have the GitHub OIDC provider, set:

```hcl
create_github_oidc_provider = true
```

Only one GitHub OIDC provider should exist per AWS account.

## Important Outputs

- `ecr_repository_url`
- `image_uri`
- `cluster_name`, `cluster_arn`
- `task_definition_family`, `task_definition_arn`
- `container_name`
- `queue_name`, `queue_url`, `dlq_name`, `dlq_url`
- `task_role_arn`, `task_execution_role_arn`
- `gha_role_arn`
- `log_group_name`
