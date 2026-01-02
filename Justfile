set shell := ["bash", "-c"]
set dotenv-load := true

# Show available recipes
[private]
default:
	@just --list

# Log in to ECR
[group: "docker"]
aws-login:
	aws ecr get-login-password --region {{env("AWS_REGION")}} | docker login --username AWS --password-stdin {{env("AWS_ACCOUNT_ID")}}.dkr.ecr.{{env("AWS_REGION")}}.amazonaws.com

# Build the container image
[group: "docker"]
build-container:
	docker buildx build --platform=linux/amd64 -t {{env("CONTAINER_NAME")}} .

# Push the image to ECR
[group: "docker"]
push-container:
	docker tag {{env("CONTAINER_NAME")}}:latest {{env("AWS_ACCOUNT_ID")}}.dkr.ecr.{{env("AWS_REGION")}}.amazonaws.com/{{env("CONTAINER_NAME")}}:latest
	docker push {{env("AWS_ACCOUNT_ID")}}.dkr.ecr.{{env("AWS_REGION")}}.amazonaws.com/{{env("CONTAINER_NAME")}}:latest

# Complete docker workflow: login, build, and push
[group: "docker"]
container: aws-login build-container push-container


# Lint the codebase
[group: "lint"]
lint package="all":
	@if [ "{{package}}" = "api" ]; then \
		cd api && uv run ruff check --fix app; \
	elif [ "{{package}}" = "dashboard-utils" ]; then \
		cd dashboard-utils && uv run ruff check --fix src; \
	elif [ "{{package}}" = "etl" ]; then \
		cd etl && uv run ruff check --fix src; \
	elif [ "{{package}}" = "all" ]; then \
		echo "Linting all packages..."; \
		cd api && uv run ruff check --fix app; \
		cd dashboard-utils && uv run ruff check --fix src; \
		cd etl && uv run ruff check --fix src; \
	else \
		echo "Unknown package: {{package}}" >&2; \
		exit 1; \
	fi

# Format the codebase
[group: "lint"]
format package="all":
	@if [ "{{package}}" = "api" ]; then \
		cd api && uv run ruff format app; \
	elif [ "{{package}}" = "dashboard-utils" ]; then \
		cd dashboard-utils && uv run ruff format src; \
	elif [ "{{package}}" = "etl" ]; then \
		cd etl && uv run ruff format src; \
	elif [ "{{package}}" = "all" ]; then \
		echo "Formatting all packages..."; \
		cd api && uv run ruff format app; \
		cd dashboard-utils && uv run ruff format src; \
		cd etl && uv run ruff format src; \
	else \
		echo "Unknown package: {{package}}" >&2; \
		exit 1; \
	fi

# Run mypy type checks
[group: "lint"]
type-check package="all":
	@if [ "{{package}}" = "api" ]; then \
		cd api && uv run mypy app; \
	elif [ "{{package}}" = "dashboard-utils" ]; then \
		cd dashboard-utils && uv run mypy src; \
	elif [ "{{package}}" = "etl" ]; then \
		cd etl && uv run mypy src; \
	elif [ "{{package}}" = "all" ]; then \
		echo "Type-checking all packages..."; \
		cd api && uv run mypy app; \
		cd dashboard-utils && uv run mypy src; \
		cd etl && uv run mypy src; \
	else \
		echo "Unknown package: {{package}}" >&2; \
		exit 1; \
	fi