variable "name" {
  type    = string
  default = "simple-scraper"
}

variable "aws_account_id" {
  type = string
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "s3_bucket" {
  type = string
}

variable "s3_prefix" {
  type    = string
  default = "simple-scraper"
}

variable "queue_name" {
  type    = string
  default = "simple-scraper"
}

variable "dlq_name" {
  type    = string
  default = "simple-scraper-dlq"
}

variable "vpc_subnet_ids" {
  type = list(string)
}

variable "vpc_security_group_ids" {
  type = list(string)
}
