set shell := ["bash", "-c"]
set dotenv-load := true

# Configuration consumed by packages/aws-batch-scraper/just/aws-batch-scraper.just.
aws_batch_scraper_cli_dir := "packages/etl"
aws_batch_scraper_cli := "gv-dashboard-etl"
aws_batch_scraper_cli_group := "courts"
aws_batch_scraper_dockerfile := "packages/etl/Dockerfile"
aws_batch_scraper_browser_lock_script := "packages/etl/scripts/render_chrome_lock.py"
# BEGIN GENERATED: chrome-lock-release-contract
aws_batch_scraper_required_sbom_packages := "python:playwright=1.63.0,deb:google-chrome-stable=155.0.8059.84-1,deb:libcurl3t64-gnutls=8.18.0-1ubuntu2.8,deb:libx11-6=2:1.8.13-1ubuntu0.1,deb:librsvg2-2=2.61.3+dfsg-3ubuntu0.1,deb:libpng16-16t64=1.6.57-1ubuntu0.1,deb:libaom3=3.13.1-2ubuntu0.1,deb:bubblewrap=0.12.0-0philly1,binary:node=24.21.0"
aws_batch_scraper_chrome_executable_sha256 := "sha256:cb19b59995072b86cc7f887b3b1c7ab1f63518a7f2ed9f0d33249e1a040e2c76"
# END GENERATED: chrome-lock-release-contract
aws_batch_scraper_chrome_sandbox_scan_args := "--forbid-chrome-sandbox --forbid-setuid-setgid-files"
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
