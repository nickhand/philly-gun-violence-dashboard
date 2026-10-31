set shell := ["bash", "-c"]
set dotenv-load := true

# Configuration consumed by packages/aws-batch-scraper/just/aws-batch-scraper.just.
aws_batch_scraper_cli_dir := "packages/etl"
aws_batch_scraper_cli := "gv-dashboard-etl"
aws_batch_scraper_cli_group := "courts"
aws_batch_scraper_dockerfile := "packages/etl/Dockerfile"
aws_batch_scraper_browser_lock_script := "packages/etl/scripts/render_chrome_lock.py"
# BEGIN GENERATED: chrome-lock-release-contract
aws_batch_scraper_required_sbom_packages := "python:playwright=1.64.1,deb:google-chrome-stable=156.0.8078.79-1,deb:libcurl3t64-gnutls=8.18.0-1ubuntu2.8,deb:libx11-6=2:1.8.13-1ubuntu0.1,deb:librsvg2-2=2.61.3+dfsg-3ubuntu0.1,deb:libpng16-16t64=1.6.57-1ubuntu0.1,deb:libaom3=3.13.1-2ubuntu0.1,deb:bubblewrap=0.12.0-0philly1,deb:ca-certificates=20260816ubuntu0.26.04.1,deb:libnss3=2:3.120-1ubuntu2.2,deb:liblzma5=5.8.3-1ubuntu0.1,deb:zlib1g=1:1.3.dfsg+really1.3.1-1ubuntu3.2,deb:libbrotli1=1.2.0-3ubuntu0.1,binary:node=24.22.1"
aws_batch_scraper_chrome_executable_sha256 := "sha256:da143614d917f346b02c1b29587cc13bf891d4b73faf2bea7b20cbd8fa61510f"
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
