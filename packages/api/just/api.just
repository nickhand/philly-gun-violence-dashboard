# API recipes.

fly_api_app := "philly-gun-violence-dashboard-api"
fly_scheduler_app := "philly-gun-violence-dashboard-scheduler"

# Run the API in development mode
[group: "api"]
api-dev:
	cd packages/api; uv run uvicorn app.main:app --reload

# Run the API in production mode
[group: "api"]
api-run:
	cd packages/api; uv run uvicorn app.main:app --host 0.0.0.0 --port 8080

# Check the API health endpoint
[group: "api"]
api-check:
	curl -s http://localhost:8000/health | jq .

# Deploy the API to Fly.io using the API Dockerfile
[group: "api-fly"]
fly-deploy-api:
	flyctl deploy --app "{{ fly_api_app }}" --config fly.toml --dockerfile packages/api/Dockerfile

# Create the isolated external scheduler app once.
[group: "api-fly"]
fly-create-scheduler:
	flyctl apps create "{{ fly_scheduler_app }}"

# Stop the legacy cron process before transferring schedule ownership.
[group: "api-fly"]
fly-stop-legacy-scheduler:
	flyctl scale count 0 --process-group cron --app "{{ fly_api_app }}" --yes
	@just fly-assert-legacy-scheduler-stopped

# Fail closed if the public API app still has any cron Machine.
[private]
fly-assert-legacy-scheduler-stopped:
	@legacy_count="$(flyctl machine list --app "{{ fly_api_app }}" --json | jq '[.[] | select((.config.metadata.fly_process_group // .config.env.FLY_PROCESS_GROUP // "") == "cron")] | length')"; \
		if [ "$legacy_count" -ne 0 ]; then \
			echo "Refusing scheduler deploy: $legacy_count legacy API cron Machine(s) still exist." >&2; \
			echo "Choose a quiet window, verify no dispatched workflow is active, then run: just fly-stop-legacy-scheduler" >&2; \
			exit 1; \
		fi

# Verify that exactly one scheduler Machine exists and is started.
[private]
fly-assert-single-scheduler:
	@counts="$(flyctl machine list --app "{{ fly_scheduler_app }}" --json | jq -r '[.[] | select((.config.metadata.fly_process_group // .config.env.FLY_PROCESS_GROUP // "") == "cron")] as $cron | "\($cron | length) \([$cron[] | select(.state == "started")] | length)"')"; \
		read -r total started <<< "$counts"; \
		if [ "$total" -ne 1 ] || [ "$started" -ne 1 ]; then \
			echo "Unsafe scheduler topology: expected one started cron Machine, found $total total / $started started." >&2; \
			exit 1; \
		fi

# Deploy the scheduler without an HTTP service or S3 credentials. The legacy
# cron guard and immediate, non-HA replacement prevent two cron owners.
[group: "api-fly"]
fly-deploy-scheduler: fly-assert-legacy-scheduler-stopped
	flyctl deploy --app "{{ fly_scheduler_app }}" --config fly.scheduler.toml --dockerfile packages/api/Dockerfile --strategy immediate --ha=false
	flyctl scale count 1 --process-group cron --app "{{ fly_scheduler_app }}" --yes
	@just fly-assert-single-scheduler

# Import .env as Fly secrets for the API app
[group: "api-fly"]
fly-secrets-api:
	@:${FLY_AWS_ACCESS_KEY_ID:?FLY_AWS_ACCESS_KEY_ID is required}
	@:${FLY_AWS_SECRET_ACCESS_KEY:?FLY_AWS_SECRET_ACCESS_KEY is required}
	@:${AWS_REGION:?AWS_REGION is required}
	@:${S3_BUCKET:?S3_BUCKET is required}
	@printf '%s\n' \
		"AWS_ACCESS_KEY_ID=${FLY_AWS_ACCESS_KEY_ID}" \
		"AWS_SECRET_ACCESS_KEY=${FLY_AWS_SECRET_ACCESS_KEY}" \
		"AWS_REGION=${AWS_REGION}" \
		"S3_BUCKET=${S3_BUCKET}" \
		| flyctl secrets import --app "{{ fly_api_app }}"

# Remove the legacy scheduler credential after schedule ownership has moved.
[group: "api-fly"]
fly-remove-legacy-api-token:
	flyctl secrets unset GITHUB_PAT --app "{{ fly_api_app }}"

# Give only the scheduler the fine-grained Actions token.
[group: "api-fly"]
fly-secrets-scheduler:
	@:${FLY_GITHUB_PAT:?FLY_GITHUB_PAT is required}
	@printf 'GITHUB_PAT=%s\n' "${FLY_GITHUB_PAT}" \
		| flyctl secrets import --app "{{ fly_scheduler_app }}"

# Fly.io authentication
[group: "api-fly"]
fly-login:
	flyctl auth login

# Show app status
[group: "api-fly"]
fly-status:
	flyctl status --app "{{ fly_api_app }}"

[group: "api-fly"]
fly-status-scheduler:
	flyctl status --app "{{ fly_scheduler_app }}"

# Open an SSH session to the app
[group: "api-fly"]
fly-ssh:
	flyctl ssh console --app "{{ fly_api_app }}"

# Show Fly logs
[group: "api-fly"]
fly-logs:
	flyctl logs --app "{{ fly_api_app }}"

[group: "api-fly"]
fly-logs-scheduler:
	flyctl logs --app "{{ fly_scheduler_app }}"

# Restart the Fly app defined in fly.toml
[group: "api-fly"]
fly-restart:
	flyctl apps restart "{{ fly_api_app }}"
