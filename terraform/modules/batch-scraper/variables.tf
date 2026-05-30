variable "name" {
  description = "Base name for all resources (e.g. 'ujs-scraper')."
  type        = string
}

variable "s3_bucket" {
  description = "Existing S3 bucket where scraper results and manifests are stored."
  type        = string
}

variable "s3_prefix" {
  description = "S3 key prefix for all scraper objects (e.g. 'ujs-scraper')."
  type        = string
}

variable "s3_extra_prefixes" {
  description = "Additional S3 prefixes the submit/process workflows need, without trailing wildcards."
  type        = list(string)
  default     = []
}

variable "queue_name" {
  description = "Main SQS queue name. Defaults to var.name."
  type        = string
  default     = null
}

variable "dlq_name" {
  description = "Dead-letter queue name. Defaults to '<queue_name>-dlq'."
  type        = string
  default     = null
}

variable "vpc_subnet_ids" {
  description = "Subnet IDs used by scraper ECS tasks; exposed as outputs for CI/runtime configuration."
  type        = list(string)
}

variable "vpc_security_group_ids" {
  description = "Security group IDs used by scraper ECS tasks; exposed as outputs for CI/runtime configuration."
  type        = list(string)
}

variable "github_repository" {
  description = "Optional GitHub repo in 'owner/repo' format for OIDC trust. Leave null to skip GitHub Actions IAM resources."
  type        = string
  default     = null
}

variable "create_github_oidc_provider" {
  description = "Create the account-level GitHub OIDC provider. Set false if it already exists."
  type        = bool
  default     = false
}

variable "container_name" {
  description = "Name of the ECS container."
  type        = string
  default     = null
}

variable "image_uri" {
  description = "Container image URI for the ECS task definition. Defaults to this module's ECR repository with the latest tag."
  type        = string
  default     = null
}

variable "container_command" {
  description = "Default command for worker tasks. The framework overrides this for monitor tasks."
  type        = list(string)
}

variable "container_cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 1024
}

variable "container_memory" {
  description = "Fargate task memory in MiB."
  type        = number
  default     = 2048
}

variable "environment" {
  description = "Non-secret environment variables injected into the ECS container."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Secret environment variables as name => Secrets Manager or SSM parameter ARN."
  type        = map(string)
  default     = {}
}

variable "assign_public_ip" {
  description = "Whether ECS task ENIs should receive a public IP."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
  default     = 30
}

variable "visibility_timeout" {
  description = "SQS visibility timeout in seconds. Should exceed the longest expected scrape."
  type        = number
  default     = 420
}

variable "max_receive_count" {
  description = "Number of delivery attempts before a message moves to the DLQ."
  type        = number
  default     = 10
}
