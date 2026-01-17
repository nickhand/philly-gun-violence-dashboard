set shell := ["bash", "-c"]
set dotenv-load := true

# Show available recipes
[private]
default:
	@just --list

# -----------------------------------------------------------------------------
# Frontend Tasks
# -----------------------------------------------------------------------------
# Install frontend dependencies
[group: "ui"]
ui-install:
	cd frontend; npm install

# Build the frontend application
[group: "ui"]
ui-build:
	cd frontend; npm run build

# Launch the development server for the frontend
[group: "ui"]
ui-dev:
	cd frontend; npm run dev

# Type check the frontend application
[group: "ui"]
ui-type-check:
	cd frontend; npm run type-check

# Lint the frontend (alias for type-check)
[group: "ui"]
ui-lint:
	cd frontend; npm run type-check

# -----------------------------------------------------------------------------
# Development
# -----------------------------------------------------------------------------

# Launch both UI and API dev servers in parallel (kills existing processes first)
[group: "dev"]
dev:
	-lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	-lsof -ti:5173 | xargs kill -9 2>/dev/null || true
	@just api-dev & just ui-dev

# -----------------------------------------------------------------------------
# ETL Commands
# -----------------------------------------------------------------------------

# ETL boundaries data
[group: "etl"]
etl-boundaries:
	cd etl; uv run gv-dashboard-etl boundaries extract

# ETL shootings data
[group: "etl"]
etl-shootings:
	cd etl; uv run gv-dashboard-etl shootings update

# ETL homicides data
[group: "etl"]
etl-homicides:
	cd etl; uv run gv-dashboard-etl homicides update

# ETL streets data
[group: "etl"]
etl-streets:
	cd etl; uv run gv-dashboard-etl streets extract && uv run gv-dashboard-etl streets load

# ETL courts data
[group: "etl"]
etl-courts ntasks='10':
	cd etl; uv run gv-dashboard-etl courts update --ntasks {{ntasks}}

# -----------------------------------------------------------------------------
# ETL Courts Scraper
# -----------------------------------------------------------------------------

# Log in to ECR
[group: "courts-scraper"]
aws-login:
	aws ecr get-login-password --region {{env("AWS_REGION")}} | docker login --username AWS --password-stdin {{env("AWS_ACCOUNT_ID")}}.dkr.ecr.{{env("AWS_REGION")}}.amazonaws.com

# Build the ETL container image for scraping courts data
[group: "courts-scraper"]
build-container:
	docker buildx build --platform=linux/amd64 -t {{env("CONTAINER_NAME")}} -f etl/Dockerfile .

# Push the ETL image to ECR
[group: "courts-scraper"]
push-container:
	docker tag {{env("CONTAINER_NAME")}}:latest {{env("AWS_ACCOUNT_ID")}}.dkr.ecr.{{env("AWS_REGION")}}.amazonaws.com/{{env("CONTAINER_NAME")}}:latest
	docker push {{env("AWS_ACCOUNT_ID")}}.dkr.ecr.{{env("AWS_REGION")}}.amazonaws.com/{{env("CONTAINER_NAME")}}:latest

# Complete docker workflow for the courts scraper: login, build, and push
[group: "courts-scraper"]
build-and-push-container: aws-login build-container push-container

# -----------------------------------------------------------------------------
# API Tasks
# -----------------------------------------------------------------------------

# Run the API in development mode
[group: "api"]
api-dev:
    cd api; uv run uvicorn app.main:app --reload

# Run the API in production mode
[group: "api"]
api-run:
    cd api; uv run uvicorn app.main:app --host 0.0.0.0 --port 8080

# Check the API health endpoint
[group: "api"]
api-check:
    curl -s http://localhost:8000/health | jq .

# -----------------------------------------------------------------------------
# API Deployment on Fly.io
# -----------------------------------------------------------------------------

# Deploy the API to Fly.io using the API Dockerfile
[group: "api-fly"]
fly-deploy-api:
	flyctl deploy --dockerfile api/Dockerfile

# Import .env as Fly secrets for the API app
[group: "api-fly"]
fly-secrets-api:
	flyctl secrets set \
		AWS_ACCESS_KEY_ID="{{ env('AWS_ACCESS_KEY_ID') }}" \
		AWS_SECRET_ACCESS_KEY="{{ env('AWS_SECRET_ACCESS_KEY') }}" \
		AWS_REGION="{{ env('AWS_REGION') }}" \
		AWS_BUCKET_NAME="{{ env('AWS_BUCKET_NAME') }}"

# Fly.io authentication
[group: "api-fly"]
fly-login:
	flyctl auth login

# Show app status
[group: "api-fly"]
fly-status:
	flyctl status

# Open an SSH session to the app
[group: "api-fly"]
fly-ssh:
	flyctl ssh console

# Show Fly logs
[group: "api-fly"]
fly-logs:
	flyctl logs

# Restart the Fly app defined in fly.toml
[group: "api-fly"]
fly-restart:
	flyctl apps restart

# -----------------------------------------------------------------------------
# Data Tasks
# -----------------------------------------------------------------------------

# Sync the S3 data bucket to the local data/ folder
[group: "data"]
data-sync:
	aws s3 sync s3://{{env("AWS_BUCKET_NAME")}} data/ --exact-timestamps --delete

# -----------------------------------------------------------------------------
# Python tools: Linting, Formatting, Type Checking
# -----------------------------------------------------------------------------

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
		cd api && uv run ruff check --fix app; cd ..; \
		cd dashboard-utils && uv run ruff check --fix src; cd ..; \
		cd etl && uv run ruff check --fix src; cd ..; \
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
		cd api && uv run ruff format app; cd ..; \
		cd dashboard-utils && uv run ruff format src; cd ..; \
		cd etl && uv run ruff format src; cd ..; \
	else \
		echo "Unknown package: {{package}}" >&2; \
		exit 1; \
	fi

# Run mypy type checks
[group: "lint"]
typecheck package="all":
	@if [ "{{package}}" = "api" ]; then \
		cd api && uv run mypy --config-file ../mypy.ini app; \
	elif [ "{{package}}" = "dashboard-utils" ]; then \
		cd dashboard-utils && uv run mypy --config-file ../mypy.ini src; \
	elif [ "{{package}}" = "etl" ]; then \
		cd etl && uv run mypy --config-file ../mypy.ini src; \
	elif [ "{{package}}" = "all" ]; then \
		echo "Type-checking all packages..."; \
		cd api && uv run mypy --config-file ../mypy.ini app; cd ..; \
		cd dashboard-utils && uv run mypy --config-file ../mypy.ini src; cd ..; \
		cd etl && uv run mypy --config-file ../mypy.ini src; cd ..;\
	else \
		echo "Unknown package: {{package}}" >&2; \
		exit 1; \
	fi
