set shell := ["bash", "-c"]
set dotenv-load := true

# Configuration consumed by packages/aws-batch-scraper/just/aws-batch-scraper.just.
aws_batch_scraper_cli_dir := "packages/etl"
aws_batch_scraper_cli := "gv-dashboard-etl"
aws_batch_scraper_cli_group := "courts"
aws_batch_scraper_dockerfile := "packages/etl/Dockerfile"
aws_batch_scraper_docker_context := "."
aws_batch_scraper_ecr_repository_name := env_var_or_default("ECR_REPOSITORY_NAME", "ujs-scraper")
aws_batch_scraper_aws_region := env_var_or_default("AWS_REGION", "us-east-1")
aws_batch_scraper_aws_account_id := env_var_or_default("AWS_ACCOUNT_ID", "")
aws_batch_scraper_aws_profile := env_var_or_default("AWS_PROFILE", "")

import "packages/api/just/api.just"
import "packages/aws-batch-scraper/just/aws-batch-scraper.just"
import "packages/etl/just/etl.just"
import "frontend/just/frontend.just"
import "just/data.just"
import "just/python.just"

# Show available recipes
[private]
default:
	@just --list

# Launch both UI and API dev servers in parallel (kills existing processes first)
[group: "dev"]
dev:
	-lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	-lsof -ti:5173 | xargs kill -9 2>/dev/null || true
	@just api-dev & just ui-dev
