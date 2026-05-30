locals {
  account_id      = data.aws_caller_identity.current.account_id
  github_oidc_arn = local.github_oidc_enabled ? one(concat(data.aws_iam_openid_connect_provider.github[*].arn, aws_iam_openid_connect_provider.github[*].arn)) : null
  s3_prefixes     = distinct(concat([var.s3_prefix], var.s3_extra_prefixes))
  s3_object_arns  = [for prefix in local.s3_prefixes : "arn:aws:s3:::${var.s3_bucket}/${prefix}/*"]
}

# ---------------------------------------------------------------------------
# ECS task execution role — ECR pull + CloudWatch logs
# ---------------------------------------------------------------------------

resource "aws_iam_role" "task_execution" {
  name = "${var.name}-task-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "task_execution_ecr_logs" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "task_execution_secrets" {
  count = length(var.secrets) > 0 ? 1 : 0

  name = "read-container-secrets"
  role = aws_iam_role.task_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "ssm:GetParameters"]
      Resource = values(var.secrets)
    }]
  })
}

# ---------------------------------------------------------------------------
# ECS task role — S3 r/w on prefix, SQS full on queue + DLQ, ECS describe-tasks
# ---------------------------------------------------------------------------

resource "aws_iam_role" "task" {
  name = "${var.name}-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "task_s3" {
  name = "s3-scraper-prefix"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = local.s3_object_arns
      },
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = "arn:aws:s3:::${var.s3_bucket}"
        Condition = {
          StringLike = {
            "s3:prefix" = [for prefix in local.s3_prefixes : "${prefix}/*"]
          }
        }
      },
    ]
  })
}

resource "aws_iam_role_policy" "task_sqs" {
  name = "sqs-full"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl",
        "sqs:ChangeMessageVisibility",
      ]
      Resource = [aws_sqs_queue.main.arn, aws_sqs_queue.dlq.arn]
    }]
  })
}

resource "aws_iam_role_policy" "task_ecs_describe" {
  name = "ecs-describe-tasks"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ecs:DescribeTasks", "ecs:ListTasks"]
      Resource = "*"
      Condition = {
        ArnLike = {
          "ecs:cluster" = aws_ecs_cluster.scraper.arn
        }
      }
    }]
  })
}

# ---------------------------------------------------------------------------
# GitHub Actions role — ECR push, ECS run-task, S3 r/w on prefix, SQS
# ---------------------------------------------------------------------------

resource "aws_iam_role" "gha" {
  count = local.github_oidc_enabled ? 1 : 0

  name = "${var.name}-gha"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = local.github_oidc_arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:*"
        }
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "gha_ecr" {
  count = local.github_oidc_enabled ? 1 : 0

  name = "ecr-push"
  role = aws_iam_role.gha[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
        ]
        Resource = aws_ecr_repository.scraper.arn
      },
    ]
  })
}

resource "aws_iam_role_policy" "gha_ecs" {
  count = local.github_oidc_enabled ? 1 : 0

  name = "ecs-run-task"
  role = aws_iam_role.gha[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask", "ecs:DescribeTasks", "ecs:ListTasks"]
        Resource = "*"
        Condition = {
          ArnLike = {
            "ecs:cluster" = aws_ecs_cluster.scraper.arn
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = "ecs:RegisterTaskDefinition"
        Resource = "*"
      },
      {
        # iam:PassRole is required by ECS to assign task/execution roles
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = [aws_iam_role.task.arn, aws_iam_role.task_execution.arn]
      },
    ]
  })
}

resource "aws_iam_role_policy" "gha_s3" {
  count = local.github_oidc_enabled ? 1 : 0

  name = "s3-scraper-prefix"
  role = aws_iam_role.gha[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = local.s3_object_arns
      },
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = "arn:aws:s3:::${var.s3_bucket}"
        Condition = {
          StringLike = {
            "s3:prefix" = [for prefix in local.s3_prefixes : "${prefix}/*"]
          }
        }
      },
    ]
  })
}

resource "aws_iam_role_policy" "gha_sqs" {
  count = local.github_oidc_enabled ? 1 : 0

  name = "sqs-submit"
  role = aws_iam_role.gha[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "sqs:SendMessage",
        "sqs:SendMessageBatch",
        "sqs:GetQueueUrl",
        "sqs:GetQueueAttributes",
      ]
      Resource = [aws_sqs_queue.main.arn, aws_sqs_queue.dlq.arn]
    }]
  })
}
