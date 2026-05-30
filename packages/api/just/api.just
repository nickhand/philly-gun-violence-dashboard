# API recipes.

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
	flyctl deploy --dockerfile packages/api/Dockerfile

# Import .env as Fly secrets for the API app
[group: "api-fly"]
fly-secrets-api:
	flyctl secrets set \
		AWS_ACCESS_KEY_ID="{{ env('FLY_AWS_ACCESS_KEY_ID') }}" \
		AWS_SECRET_ACCESS_KEY="{{ env('FLY_AWS_SECRET_ACCESS_KEY') }}" \
		AWS_REGION="{{ env('AWS_REGION') }}" \
		S3_BUCKET="{{ env('S3_BUCKET') }}" \
		GITHUB_PAT="{{ env('GITHUB_TOKEN') }}"

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
