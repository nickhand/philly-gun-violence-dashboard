set shell := ["bash", "-c"]
set dotenv-load := true

# Configuration consumed by packages/aws-batch-scraper/just/aws-batch-scraper.just.
aws_batch_scraper_cli_dir := "packages/etl"
aws_batch_scraper_cli := "gv-dashboard-etl"
aws_batch_scraper_cli_group := "courts"
aws_batch_scraper_dockerfile := "packages/etl/Dockerfile"
aws_batch_scraper_browser_freshness_script := "packages/etl/src/etl/chrome_release.py"
aws_batch_scraper_required_sbom_packages := "python:playwright=1.62.0,deb:google-chrome-stable=151.0.7922.169-1,binary:node=24.18.1"
aws_batch_scraper_chrome_executable_sha256 := "sha256:3059e7448d906793a7116351739d3096d232d1516e8bf19209b1e2957d5e7662"
aws_batch_scraper_chrome_sandbox_sha256 := "sha256:18391bf9d217ddbde9956347cbb1346d2808a73ade4baa3f88a610447cf946b4"
aws_batch_scraper_release_evidence_root := ".artifacts/aws-batch-scraper/releases"
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
