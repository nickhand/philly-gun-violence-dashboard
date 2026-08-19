# Reusable just recipes for projects using aws-batch-scraper.
#
# Import this file from a project Justfile after defining the variables below:
#
#   aws_batch_scraper_cli_dir := "etl"
#   aws_batch_scraper_cli := "gv-dashboard-etl"
#   aws_batch_scraper_cli_group := "courts"
#   aws_batch_scraper_dockerfile := "packages/etl/Dockerfile"
#   aws_batch_scraper_browser_freshness_script := "etl/src/etl/chrome_release.py"
#   aws_batch_scraper_required_sbom_packages := "python:playwright=..."
#   aws_batch_scraper_chrome_executable_sha256 := "sha256:..."
#   aws_batch_scraper_chrome_sandbox_scan_args := "--forbid-chrome-sandbox ..."
#   aws_batch_scraper_release_evidence_root := ".artifacts/aws-batch-scraper/releases"
#
# Release recipes read AWS_ACCOUNT_ID, AWS_REGION, ECR_REPOSITORY_NAME,
# SCRAPER_IMAGE_TAG, and optional AWS_PROFILE directly from the environment so
# no environment-derived value is interpolated into shell source by Just.

aws_batch_scraper_platform := "linux/amd64"

# Fail before build or push when the project's signed browser-release check
# says its repo-controlled pin is no longer current.
[private]
scraper-check-browser-freshness:
	python3 "{{aws_batch_scraper_browser_freshness_script}}"

# Reject unsafe environment-derived shell arguments before login or Docker.
# The Python preflight additionally proves clean-source identity and exact ECR
# registry/repository policy before every build and push.
[private]
scraper-require-release-target:
	@if ! printf '%s\n' "${SCRAPER_IMAGE_TAG:-}" | grep -Eq '^[0-9a-f]{40}$'; then \
		echo "Set SCRAPER_IMAGE_TAG to the full 40-character Git HEAD SHA." >&2; \
		exit 1; \
	fi
	@if ! printf '%s\n' "${AWS_ACCOUNT_ID:-}" | grep -Eq '^[0-9]{12}$'; then \
		echo "AWS_ACCOUNT_ID must contain exactly 12 digits." >&2; \
		exit 1; \
	fi
	@if ! printf '%s\n' "${AWS_REGION:-us-east-1}" | grep -Eq '^[a-z]{2}(-[a-z0-9]+)+-[0-9]+$'; then \
		echo "AWS_REGION is invalid." >&2; \
		exit 1; \
	fi
	@if ! printf '%s\n' "${ECR_REPOSITORY_NAME:-ujs-scraper}" | grep -Eq '^[a-z0-9]+([._/-][a-z0-9]+)*$'; then \
		echo "ECR_REPOSITORY_NAME is invalid." >&2; \
		exit 1; \
	fi
	@if [ -n "${AWS_PROFILE:-}" ] && ! printf '%s\n' "$AWS_PROFILE" | grep -Eq '^[A-Za-z0-9_.@+-]+$'; then \
		echo "AWS_PROFILE is invalid." >&2; \
		exit 1; \
	fi

# Log in to the configured ECR registry.
[group: "aws-batch-scraper"]
scraper-aws-login: scraper-require-release-target
	@if [ -n "${AWS_PROFILE:-}" ]; then \
		aws --profile "$AWS_PROFILE" --region "${AWS_REGION:-us-east-1}" ecr get-login-password; \
	else \
		aws --region "${AWS_REGION:-us-east-1}" ecr get-login-password; \
	fi | docker login --username AWS --password-stdin \
		"${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION:-us-east-1}.amazonaws.com"

# Build the scraper container image locally.
[group: "aws-batch-scraper"]
scraper-build-container: scraper-require-release-target scraper-check-browser-freshness
	cd packages/aws-batch-scraper; uv run aws-batch-scraper-release-image preflight --account-id "${AWS_ACCOUNT_ID}" --repository "${ECR_REPOSITORY_NAME:-ujs-scraper}" --region "${AWS_REGION:-us-east-1}" --tag "${SCRAPER_IMAGE_TAG}" --profile "${AWS_PROFILE:-}"
	@set -euo pipefail; git archive --format=tar HEAD | docker buildx build --load --platform="{{aws_batch_scraper_platform}}" --label "org.opencontainers.image.revision=${SCRAPER_IMAGE_TAG}" -t "${ECR_REPOSITORY_NAME:-ujs-scraper}:${SCRAPER_IMAGE_TAG}" -f "{{aws_batch_scraper_dockerfile}}" -

# Generate exact-image SBOMs and run the offline local vulnerability gates.
[group: "aws-batch-scraper"]
scraper-scan-container: scraper-require-release-target
	@cd packages/aws-batch-scraper; uv run aws-batch-scraper-release-image scan-local-image --image "${ECR_REPOSITORY_NAME:-ujs-scraper}:${SCRAPER_IMAGE_TAG}" --expected-distro-name ubuntu --expected-distro-version 26.04 --required-packages "{{aws_batch_scraper_required_sbom_packages}}" --required-chrome-executable-sha256 "{{aws_batch_scraper_chrome_executable_sha256}}" {{aws_batch_scraper_chrome_sandbox_scan_args}}

# Push the exact locally scanned image ID to ECR.
[group: "aws-batch-scraper"]
scraper-push-container: scraper-require-release-target scraper-check-browser-freshness
	cd packages/aws-batch-scraper; uv run aws-batch-scraper-release-image preflight --account-id "${AWS_ACCOUNT_ID}" --repository "${ECR_REPOSITORY_NAME:-ujs-scraper}" --region "${AWS_REGION:-us-east-1}" --tag "${SCRAPER_IMAGE_TAG}" --profile "${AWS_PROFILE:-}"
	cd packages/aws-batch-scraper; uv run aws-batch-scraper-release-image verify-local-image --image "${ECR_REPOSITORY_NAME:-ujs-scraper}:${SCRAPER_IMAGE_TAG}" --tag "${SCRAPER_IMAGE_TAG}"
	@set -euo pipefail; \
	repository_root="$(git rev-parse --show-toplevel)"; \
	scan_output_directory="${repository_root}/{{aws_batch_scraper_release_evidence_root}}/${SCRAPER_IMAGE_TAG}"; \
	scan_identity="$(cd packages/aws-batch-scraper && uv run aws-batch-scraper-release-image scan-local-image --image "${ECR_REPOSITORY_NAME:-ujs-scraper}:${SCRAPER_IMAGE_TAG}" --expected-distro-name ubuntu --expected-distro-version 26.04 --required-packages "{{aws_batch_scraper_required_sbom_packages}}" --required-chrome-executable-sha256 "{{aws_batch_scraper_chrome_executable_sha256}}" {{aws_batch_scraper_chrome_sandbox_scan_args}} --output-directory "${scan_output_directory}" --print-identity)"; \
	if [[ "${scan_identity}" == *$'\n'* ]]; then \
		echo "Local scanner returned more than one identity line." >&2; exit 1; \
	fi; \
	read -r scanned_image_id scanned_manifest_digest extra <<< "${scan_identity}"; \
	if ! printf '%s\n' "${scanned_image_id}" | grep -Eq '^sha256:[0-9a-f]{64}$' || \
	   ! printf '%s\n' "${scanned_manifest_digest}" | grep -Eq '^sha256:[0-9a-f]{64}$' || \
	   [ -n "${extra}" ]; then \
		echo "Local scanner returned an invalid image identity." >&2; exit 1; \
	fi; \
	(cd packages/aws-batch-scraper && uv run aws-batch-scraper-release-image verify-local-image --image "${scanned_image_id}" --tag "${SCRAPER_IMAGE_TAG}"); \
	docker tag "${scanned_image_id}" "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION:-us-east-1}.amazonaws.com/${ECR_REPOSITORY_NAME:-ujs-scraper}:${SCRAPER_IMAGE_TAG}"; \
	docker push "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION:-us-east-1}.amazonaws.com/${ECR_REPOSITORY_NAME:-ujs-scraper}:${SCRAPER_IMAGE_TAG}"; \
	cd packages/aws-batch-scraper; uv run aws-batch-scraper-release-image verify-scan --account-id "${AWS_ACCOUNT_ID}" --repository "${ECR_REPOSITORY_NAME:-ujs-scraper}" --region "${AWS_REGION:-us-east-1}" --tag "${SCRAPER_IMAGE_TAG}" --profile "${AWS_PROFILE:-}" --expected-image-id "${scanned_image_id}" --local-scan-receipt "${scan_output_directory}/receipt.json" --release-receipt "${scan_output_directory}/release.json"

# Complete container workflow: login, build, and push.
[group: "aws-batch-scraper"]
scraper-build-and-push-container: scraper-require-release-target scraper-aws-login scraper-build-container scraper-push-container

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
