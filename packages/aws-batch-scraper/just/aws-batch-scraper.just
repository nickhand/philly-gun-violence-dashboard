# Reusable just recipes for projects using aws-batch-scraper.
#
# Import this file from a project Justfile after defining the variables below:
#
#   aws_batch_scraper_cli_dir := "etl"
#   aws_batch_scraper_cli := "gv-dashboard-etl"
#   aws_batch_scraper_cli_group := "courts"
#   aws_batch_scraper_dockerfile := "packages/etl/Dockerfile"
#   aws_batch_scraper_docker_context := "."
#   aws_batch_scraper_ecr_repository_name := env_var_or_default("ECR_REPOSITORY_NAME", "ujs-scraper")
#   aws_batch_scraper_aws_region := env_var_or_default("AWS_REGION", "us-east-1")
#   aws_batch_scraper_aws_account_id := env("AWS_ACCOUNT_ID")
#   aws_batch_scraper_aws_profile := env_var_or_default("AWS_PROFILE", "")

aws_batch_scraper_platform := "linux/amd64"
aws_batch_scraper_image_tag := "latest"
aws_batch_scraper_ecr_image_uri := aws_batch_scraper_aws_account_id + ".dkr.ecr." + aws_batch_scraper_aws_region + ".amazonaws.com/" + aws_batch_scraper_ecr_repository_name + ":" + aws_batch_scraper_image_tag

# Log in to the configured ECR registry.
[group: "aws-batch-scraper"]
scraper-aws-login:
	@if [ -z "{{aws_batch_scraper_aws_account_id}}" ]; then \
		echo "AWS_ACCOUNT_ID is required for ECR login." >&2; \
		exit 1; \
	fi
	@profile_arg=""; \
	if [ -n "{{aws_batch_scraper_aws_profile}}" ]; then \
		profile_arg="--profile {{aws_batch_scraper_aws_profile}}"; \
	fi; \
	aws ecr get-login-password --region "{{aws_batch_scraper_aws_region}}" $profile_arg \
		| docker login --username AWS --password-stdin "{{aws_batch_scraper_aws_account_id}}.dkr.ecr.{{aws_batch_scraper_aws_region}}.amazonaws.com"

# Build the scraper container image locally.
[group: "aws-batch-scraper"]
scraper-build-container:
	docker buildx build --platform={{aws_batch_scraper_platform}} -t {{aws_batch_scraper_ecr_repository_name}} -f {{aws_batch_scraper_dockerfile}} {{aws_batch_scraper_docker_context}}

# Push the scraper container image to ECR.
[group: "aws-batch-scraper"]
scraper-push-container:
	@if [ -z "{{aws_batch_scraper_aws_account_id}}" ]; then \
		echo "AWS_ACCOUNT_ID is required for ECR push." >&2; \
		exit 1; \
	fi
	docker tag {{aws_batch_scraper_ecr_repository_name}}:latest {{aws_batch_scraper_ecr_image_uri}}
	docker push {{aws_batch_scraper_ecr_image_uri}}

# Complete container workflow: login, build, and push.
[group: "aws-batch-scraper"]
scraper-build-and-push-container: scraper-aws-login scraper-build-container scraper-push-container

# Seed the queue and launch workers.
[group: "aws-batch-scraper"]
scraper-submit *ARGS:
	cd {{aws_batch_scraper_cli_dir}}; uv run {{aws_batch_scraper_cli}} {{aws_batch_scraper_cli_group}} submit {{ARGS}}

# Monitor a run until completion.
[group: "aws-batch-scraper"]
scraper-monitor *ARGS:
	cd {{aws_batch_scraper_cli_dir}}; uv run {{aws_batch_scraper_cli}} {{aws_batch_scraper_cli_group}} monitor {{ARGS}}

# Aggregate per-item scraper results from S3.
[group: "aws-batch-scraper"]
scraper-aggregate *ARGS:
	cd {{aws_batch_scraper_cli_dir}}; uv run {{aws_batch_scraper_cli}} {{aws_batch_scraper_cli_group}} aggregate {{ARGS}}

# Print stats for a scraper run.
[group: "aws-batch-scraper"]
scraper-run-stats *ARGS:
	cd {{aws_batch_scraper_cli_dir}}; uv run {{aws_batch_scraper_cli}} {{aws_batch_scraper_cli_group}} run-stats {{ARGS}}

# Print permanent failures for a scraper run.
[group: "aws-batch-scraper"]
scraper-failures *ARGS:
	cd {{aws_batch_scraper_cli_dir}}; uv run {{aws_batch_scraper_cli}} {{aws_batch_scraper_cli_group}} failures {{ARGS}}

# Benchmark the scraper locally.
[group: "aws-batch-scraper"]
scraper-bench *ARGS:
	cd {{aws_batch_scraper_cli_dir}}; uv run {{aws_batch_scraper_cli}} {{aws_batch_scraper_cli_group}} bench {{ARGS}}
