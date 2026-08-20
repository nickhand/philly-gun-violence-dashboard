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

# Wait for Fly's asynchronous Machine start, then verify that exactly one
# scheduler Machine exists and is started.
[private]
fly-assert-single-scheduler:
	@scheduler_start_timeout_seconds=120; \
		scheduler_start_poll_seconds=5; \
		scheduler_wait_started_at="$(date +%s)"; \
		echo "Waiting up to ${scheduler_start_timeout_seconds}s for one scheduler cron Machine to start..."; \
		while true; do \
			machine_list="$(flyctl machine list --app "{{ fly_scheduler_app }}" --json)" || { \
				echo "Unable to inspect scheduler Machines; refusing to continue." >&2; \
				exit 1; \
			}; \
			total="$(jq -er 'if type == "array" then length else error("expected an array") end' <<< "$machine_list")" || { \
				echo "Unable to parse the scheduler Machine list; refusing to continue." >&2; \
				exit 1; \
			}; \
			if [ "$total" -gt 1 ]; then \
				echo "Unsafe scheduler topology: expected at most one Machine in the scheduler app while starting, found $total." >&2; \
				exit 1; \
			fi; \
			if [ "$total" -eq 1 ]; then \
				process_group="$(jq -er '.[0] | (.config.metadata.fly_process_group // .config.env.FLY_PROCESS_GROUP // empty) | strings | select(length > 0)' <<< "$machine_list")" || { \
					echo "The sole scheduler Machine has no valid process group; refusing to continue." >&2; \
					exit 1; \
				}; \
				if [ "$process_group" != "cron" ]; then \
					echo "The sole scheduler Machine belongs to process group '$process_group', not 'cron'; refusing to continue." >&2; \
					exit 1; \
				fi; \
				state="$(jq -er '.[0].state | strings | select(length > 0)' <<< "$machine_list")" || { \
					echo "The sole scheduler Machine has no valid state; refusing to continue." >&2; \
					exit 1; \
				}; \
				case "$state" in \
					started) \
						echo "Verified exactly one started scheduler cron Machine."; \
						exit 0 \
						;; \
					created|creating|starting|restarting|updating|replacing) \
						;; \
					stopping|stopped|suspending|suspended|failed|destroying|destroyed) \
						echo "Scheduler cron Machine entered down or terminal state '$state'; refusing to continue." >&2; \
						exit 1 \
						;; \
					*) \
						echo "Scheduler cron Machine entered unexpected state '$state'; refusing to continue." >&2; \
						exit 1 \
						;; \
				esac; \
			fi; \
			elapsed_seconds=$(( $(date +%s) - scheduler_wait_started_at )); \
			if [ "$elapsed_seconds" -ge "$scheduler_start_timeout_seconds" ]; then \
				echo "Timed out after ${scheduler_start_timeout_seconds}s waiting for exactly one started scheduler cron Machine; found $total Machine(s)." >&2; \
				exit 1; \
			fi; \
			remaining_seconds=$(( scheduler_start_timeout_seconds - elapsed_seconds )); \
			sleep_seconds="$scheduler_start_poll_seconds"; \
			if [ "$remaining_seconds" -lt "$sleep_seconds" ]; then sleep_seconds="$remaining_seconds"; fi; \
			sleep "$sleep_seconds"; \
		done

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
