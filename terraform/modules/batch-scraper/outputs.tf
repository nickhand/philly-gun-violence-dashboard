output "queue_url" {
  description = "URL of the main SQS work queue."
  value       = aws_sqs_queue.main.url
}

output "queue_name" {
  description = "Name of the main SQS work queue."
  value       = aws_sqs_queue.main.name
}

output "dlq_url" {
  description = "URL of the dead-letter queue."
  value       = aws_sqs_queue.dlq.url
}

output "dlq_name" {
  description = "Name of the dead-letter queue."
  value       = aws_sqs_queue.dlq.name
}

output "cluster_arn" {
  description = "ARN of the ECS Fargate cluster."
  value       = aws_ecs_cluster.scraper.arn
}

output "cluster_name" {
  description = "Name of the ECS Fargate cluster."
  value       = aws_ecs_cluster.scraper.name
}

output "ecr_repository_url" {
  description = "ECR repository URL for pushing container images."
  value       = aws_ecr_repository.scraper.repository_url
}

output "image_uri" {
  description = "Image URI used by the ECS task definition."
  value       = local.image_uri
}

output "task_definition_arn" {
  description = "ARN of the ECS task definition."
  value       = aws_ecs_task_definition.scraper.arn
}

output "task_definition_family" {
  description = "Family/name of the ECS task definition."
  value       = aws_ecs_task_definition.scraper.family
}

output "container_name" {
  description = "Name of the ECS container."
  value       = local.container_name
}

output "task_role_arn" {
  description = "ARN of the ECS task role (runtime permissions)."
  value       = aws_iam_role.task.arn
}

output "task_execution_role_arn" {
  description = "ARN of the ECS task execution role (ECR pull + CloudWatch logs)."
  value       = aws_iam_role.task_execution.arn
}

output "gha_role_arn" {
  description = "ARN of the GitHub Actions OIDC role."
  value       = local.github_oidc_enabled ? aws_iam_role.gha[0].arn : null
}

output "log_group_name" {
  description = "CloudWatch log group name for ECS task logs."
  value       = aws_cloudwatch_log_group.scraper.name
}

output "vpc_subnet_ids" {
  description = "Subnet IDs to pass to scraper submitter configuration."
  value       = var.vpc_subnet_ids
}

output "vpc_security_group_ids" {
  description = "Security group IDs to pass to scraper submitter configuration."
  value       = var.vpc_security_group_ids
}
