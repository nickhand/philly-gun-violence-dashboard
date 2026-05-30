variable "s3_bucket" {
  description = "S3 bucket for scraper data and Terraform state."
  type        = string
}

variable "vpc_subnet_ids" {
  description = "Subnet IDs for ECS Fargate tasks."
  type        = list(string)
}

variable "vpc_security_group_ids" {
  description = "Security group IDs for ECS Fargate tasks."
  type        = list(string)
}

variable "github_dispatch_token_secret_arn" {
  description = "Secrets Manager or SSM parameter ARN containing GITHUB_DISPATCH_TOKEN for the ECS monitor task."
  type        = string
  default     = null
}
