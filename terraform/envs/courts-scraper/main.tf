terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

data "aws_caller_identity" "current" {}

module "courts_scraper" {
  source = "../../modules/batch-scraper"

  name                   = "ujs-scraper"
  s3_bucket              = var.s3_bucket
  s3_prefix              = "ujs-scraper"
  s3_extra_prefixes      = ["processed/shootings", "processed/courts"]
  queue_name             = "ujs-incidents"
  dlq_name               = "ujs-incidents-dlq"
  vpc_subnet_ids         = var.vpc_subnet_ids
  vpc_security_group_ids = var.vpc_security_group_ids
  github_repository      = "nhand21/philly-gun-violence-dashboard"

  container_command = ["uv", "run", "gv-dashboard-etl", "courts", "worker"]
  container_cpu     = 1024
  container_memory  = 2048

  environment = {
    ENV                    = "prod"
    AWS_ACCOUNT_ID         = data.aws_caller_identity.current.account_id
    AWS_REGION             = "us-east-1"
    S3_BUCKET              = var.s3_bucket
    S3_SCRAPER_PREFIX      = "ujs-scraper"
    SQS_QUEUE_NAME         = "ujs-incidents"
    SQS_DLQ_NAME           = "ujs-incidents-dlq"
    ECS_CLUSTER_NAME       = "ujs-scraper"
    ECS_TASK_DEFINITION    = "ujs-scraper"
    ECS_CONTAINER_NAME     = "ujs-scraper"
    ECS_SUBNET_IDS         = join(",", var.vpc_subnet_ids)
    ECS_SECURITY_GROUP_IDS = join(",", var.vpc_security_group_ids)
    GITHUB_REPOSITORY      = "nhand21/philly-gun-violence-dashboard"
    SOFT_BLOCKED_DELAY_MIN = "300"
    SOFT_BLOCKED_DELAY_MAX = "900"
  }

  secrets = var.github_dispatch_token_secret_arn == null ? {} : {
    GITHUB_DISPATCH_TOKEN = var.github_dispatch_token_secret_arn
  }

  visibility_timeout = 420
  max_receive_count  = 10
}

output "queue_url" { value = module.courts_scraper.queue_url }
output "queue_name" { value = module.courts_scraper.queue_name }
output "dlq_url" { value = module.courts_scraper.dlq_url }
output "dlq_name" { value = module.courts_scraper.dlq_name }
output "cluster_arn" { value = module.courts_scraper.cluster_arn }
output "cluster_name" { value = module.courts_scraper.cluster_name }
output "ecr_repository_url" { value = module.courts_scraper.ecr_repository_url }
output "image_uri" { value = module.courts_scraper.image_uri }
output "task_definition_arn" { value = module.courts_scraper.task_definition_arn }
output "task_definition_family" { value = module.courts_scraper.task_definition_family }
output "container_name" { value = module.courts_scraper.container_name }
output "task_role_arn" { value = module.courts_scraper.task_role_arn }
output "task_execution_role_arn" { value = module.courts_scraper.task_execution_role_arn }
output "gha_role_arn" { value = module.courts_scraper.gha_role_arn }
output "log_group_name" { value = module.courts_scraper.log_group_name }
output "vpc_subnet_ids" { value = module.courts_scraper.vpc_subnet_ids }
output "vpc_security_group_ids" { value = module.courts_scraper.vpc_security_group_ids }
