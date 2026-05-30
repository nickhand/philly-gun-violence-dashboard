terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  container_name      = coalesce(var.container_name, var.name)
  image_uri           = coalesce(var.image_uri, "${aws_ecr_repository.scraper.repository_url}:latest")
  github_oidc_enabled = var.github_repository != null && var.github_repository != ""
  queue_name          = coalesce(var.queue_name, var.name)
  dlq_name            = coalesce(var.dlq_name, "${local.queue_name}-dlq")
}

# ---------------------------------------------------------------------------
# SQS — main queue + DLQ
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "dlq" {
  name                      = local.dlq_name
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "main" {
  name                       = local.queue_name
  visibility_timeout_seconds = var.visibility_timeout
  message_retention_seconds  = 1209600

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
}

# ---------------------------------------------------------------------------
# ECR — container image registry
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "scraper" {
  name                 = var.name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "scraper" {
  repository = aws_ecr_repository.scraper.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 5 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}

# ---------------------------------------------------------------------------
# ECS — cluster for scraper worker and monitor tasks
# ---------------------------------------------------------------------------

resource "aws_ecs_cluster" "scraper" {
  name = var.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_cluster_capacity_providers" "scraper" {
  cluster_name       = aws_ecs_cluster.scraper.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

# ---------------------------------------------------------------------------
# CloudWatch — log group for ECS tasks
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "scraper" {
  name              = "/ecs/${var.name}"
  retention_in_days = var.log_retention_days
}

# ---------------------------------------------------------------------------
# ECS task definition — default worker command, monitor uses command override
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "scraper" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.container_cpu)
  memory                   = tostring(var.container_memory)
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = local.container_name
      image     = local.image_uri
      essential = true
      command   = var.container_command
      environment = [
        for name, value in var.environment : {
          name  = name
          value = value
        }
      ]
      secrets = [
        for name, value_from in var.secrets : {
          name      = name
          valueFrom = value_from
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.scraper.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = local.container_name
        }
      }
    }
  ])
}

# ---------------------------------------------------------------------------
# IAM — optional GitHub OIDC provider
# ---------------------------------------------------------------------------

data "aws_region" "current" {}

data "aws_iam_openid_connect_provider" "github" {
  count = local.github_oidc_enabled && !var.create_github_oidc_provider ? 1 : 0
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  count = local.github_oidc_enabled && var.create_github_oidc_provider ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}
