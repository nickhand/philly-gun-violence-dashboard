terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

module "scraper" {
  source = "../../../../terraform/modules/batch-scraper"

  name                   = var.name
  s3_bucket              = var.s3_bucket
  s3_prefix              = var.s3_prefix
  queue_name             = var.queue_name
  dlq_name               = var.dlq_name
  vpc_subnet_ids         = var.vpc_subnet_ids
  vpc_security_group_ids = var.vpc_security_group_ids

  # Leave null to skip GitHub Actions OIDC resources.
  github_repository = null

  container_command = ["simple-scraper", "scraper", "worker"]

  environment = {
    ENV                    = "prod"
    AWS_ACCOUNT_ID         = var.aws_account_id
    AWS_REGION             = var.aws_region
    S3_BUCKET              = var.s3_bucket
    S3_SCRAPER_PREFIX      = var.s3_prefix
    SQS_QUEUE_NAME         = var.queue_name
    SQS_DLQ_NAME           = var.dlq_name
    ECS_CLUSTER_NAME       = var.name
    ECS_TASK_DEFINITION    = var.name
    ECS_CONTAINER_NAME     = var.name
    ECS_SUBNET_IDS         = join(",", var.vpc_subnet_ids)
    ECS_SECURITY_GROUP_IDS = join(",", var.vpc_security_group_ids)
  }
}

output "ecr_repository_url" {
  value = module.scraper.ecr_repository_url
}

output "task_definition_family" {
  value = module.scraper.task_definition_family
}
