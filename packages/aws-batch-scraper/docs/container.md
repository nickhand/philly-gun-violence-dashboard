# Container Contract

`aws-batch-scraper` does not require a public base image. Scrapers have very
different runtime needs, so the stable interface is a container contract plus
copyable Dockerfile templates.

## Required Behavior

Your container image must:

- install your scraper package and `aws-batch-scraper`
- expose the CLI you built with `create_cli(...)`
- default to the worker command, for example:

  ```dockerfile
  CMD ["my-scraper", "scraper", "worker"]
  ```

- support the monitor command as an ECS command override:

  ```bash
  my-scraper scraper monitor --run-id <run_id>
  ```

  The framework invokes this installed console script directly. `uv` is a
  build/development tool and is not part of the runtime container contract.

- read runtime config from environment variables injected by ECS
- rely on the ECS task role for AWS credentials
- never bake AWS keys or tokens into the image

The worker and monitor task definitions must explicitly run the image's `app`
user and set `readonlyRootFilesystem: true`; submitter preflight rejects either
omission. Keep installed code owned by the image build user and mount an
explicit writable temporary volume for the paths required by the scraper.
Browser containers commonly need `/tmp`; route `HOME`, `TMPDIR`, and XDG
cache/config state to that mount and test the image before registration. For a
non-root Fargate task, declare that exact path with a Dockerfile `VOLUME` after
setting its intended ownership and permissions; otherwise an empty bind mount
defaults to root ownership and may not be writable by the runtime user.

## Runtime Environment

Provide runtime configuration to the submitter through its environment or
deployment system. It passes nonsecret values into worker and monitor tasks as
ECS overrides, so the monitor definition does not need to hard-code its own
revision. Common variables are:

```text
ENV=prod
AWS_ACCOUNT_ID=123456789012
AWS_REGION=us-east-1
S3_BUCKET=my-scraper-bucket
S3_SCRAPER_PREFIX=my-scraper
SQS_QUEUE_NAME=my-scraper
SQS_DLQ_NAME=my-scraper-dlq
ECS_CLUSTER_NAME=my-scraper
ECS_TASK_DEFINITION=my-scraper:42
ECS_MONITOR_TASK_DEFINITION=my-scraper-monitor:17
ECS_EXPECTED_IMAGE_URI=123456789012.dkr.ecr.us-east-1.amazonaws.com/my-scraper@sha256:<64-lowercase-hex>
ECS_EXPECTED_TASK_ROLE_ARN=arn:aws:iam::123456789012:role/my-scraper-task
ECS_EXPECTED_EXECUTION_ROLE_ARN=arn:aws:iam::123456789012:role/my-scraper-execution
ECS_EXPECTED_MONITOR_SECRET_ARN=arn:aws:secretsmanager:us-east-1:123456789012:secret:my-scraper/github-dispatch-token-AbCdEf
ECS_PLATFORM_VERSION=1.4.0
ECS_CONTAINER_NAME=my-scraper
ECS_SUBNET_IDS=subnet-a,subnet-b
ECS_SECURITY_GROUP_IDS=sg-a
GITHUB_REPOSITORY=owner/repository
GITHUB_WORKFLOW_FILE=process-results.yml
```

`RUN_ID` is set by the submitter when launching worker and monitor tasks.
Keep `GITHUB_DISPATCH_TOKEN` out of this environment and only in the monitor
definition's ECS `secrets` list. Use a repository-scoped fine-grained token
with **Actions: read and write**; workflow dispatch does not require
**Contents: write**.

## Build And Push To ECR

After your ECR repository exists:

```bash
export AWS_ACCOUNT_ID=123456789012
export AWS_REGION=us-east-1
export ECR_REPOSITORY_NAME=my-scraper
export SCRAPER_IMAGE_TAG="$(git rev-parse HEAD)"
just scraper-build-and-push-container
```

Before the push, configure the ECR repository with immutable tags and automatic
scanning. The guarded recipe first downloads a fresh Grype database in a
container that cannot see the target, saves the exact local image as an archive,
and runs digest-pinned Syft and Grype containers with networking disabled.
Neither scanner receives the Docker socket or registry credentials. The gate
validates tool/schema identity, database hash and age, provider timestamps,
image identity, and repo-controlled package/file contracts. It rejects every
Critical, High, or Unknown local result, including unfixed findings, and rejects
ignore rules, VEX, path exclusions, malformed reports, and stale databases.

Successful optional `--output-directory` evidence contains Syft and CycloneDX
SBOMs, Grype reports, and `receipt.json`. The receipt binds their SHA-256 digests
to the exact image, scanner images, database, and package versions. A failed scan
never emits a receipt; diagnostic files are prefixed `UNVERIFIED-` and accompanied
by `FAILED.json`. See Anchore's [supported OS matrix](https://oss.anchore.com/docs/capabilities/all-os/),
[SBOM format guide](https://oss.anchore.com/docs/guides/sbom/formats/), and
[filtering guide](https://oss.anchore.com/docs/guides/vulnerability/filter-results/).

Tag immutability is an external release gate: the local absence check cannot
eliminate a race with another publisher. The recipe tags the exact scanned image
ID, confirms the pushed manifest's config digest is that image ID, binds every
ECR call to `AWS_ACCOUNT_ID`, requires scan-on-push, and polls the remote scan for
about 30 minutes. It also hashes the exact returned manifest bytes, requires a
fresh push-bound `COMPLETE` scan and vulnerability-source update, and rejects
Undefined remote findings. `ACTIVE` enhanced-scanning state is deliberately not
treated as a completed snapshot. It prints `repository@sha256:...` only after
both gates pass. Terminal, stale, malformed, unauthorized, and timeout outcomes
exit nonzero without printing a URI. Do not replace it with an unguarded manual
`docker push` sequence.

The guarded push preserves the exact release scan under
`.artifacts/aws-batch-scraper/releases/<commit>/`. After the remote gate passes,
`release.json` binds the ECR digest and URI to the local image ID, manifest,
receipt hash, and every re-hashed SBOM/report artifact. The verified URI is not
printed unless that release receipt is written successfully. Archive this
directory with the release records; the leading-dot directory is intentionally
outside the immutable `git archive HEAD` build context.

Register separate worker and monitor ECS task-definition revisions using the
printed digest URI. Set `ECS_EXPECTED_IMAGE_URI` to that exact same-account,
same-region `repository@sha256:...` value. Do not point either definition at
`:latest`: a mutable tag cannot prove which worker protocol a run used. Each
task definition must still use `repository@sha256:...` even when ECR tag
immutability is enabled.

Set `ECS_TASK_DEFINITION` to the exact worker `family:revision` (or full
revisioned ARN) and `ECS_MONITOR_TASK_DEFINITION` to a different exact monitor
revision. Bare family names and a shared worker/monitor revision are rejected at
configuration and launch boundaries. Only the monitor definition may inject
`GITHUB_DISPATCH_TOKEN`. The current contract binds both definitions to the
single exact task role and execution role configured below. A separate worker
execution role would require distinct expected-role settings before it can be
used without weakening the fail-closed preflight.

The submitter resolves both definitions before the first durable mutation and
again at each launch boundary. It requires an ACTIVE cluster; ACTIVE Fargate
definitions using `awsvpc` and `LINUX/X86_64`; exactly one container named
by `ECS_CONTAINER_NAME`, running as the image's `app` user; the exact
`ECS_EXPECTED_IMAGE_URI`; a read-only root filesystem; and one ephemeral volume
mounted read-write only at `/tmp`. It rejects privileged containers, added
capabilities, a capability-drop list other than exactly `ALL`, extra mounts or
containers, kernel overrides, and entry-point overrides. The worker definition
must have empty `secrets`, `environment`, and `environmentFiles`; reviewed
nonsecret values arrive only through per-run ECS overrides. The primary monitor
definition must have no static environment and exactly one ECS secret,
`GITHUB_DISPATCH_TOKEN`, bound to the exact `valueFrom` ARN in
`ECS_EXPECTED_MONITOR_SECRET_ARN`. Its static command must be exactly
`["/bin/false"]`; the framework supplies the real monitor command as a launch
override, while a direct no-override launch exits without starting the browser.
Every launch explicitly pins Fargate platform
version `1.4.0` rather than accepting `LATEST`.
Both definitions must also use the exact same-account task and execution roles
named by `ECS_EXPECTED_TASK_ROLE_ARN` and `ECS_EXPECTED_EXECUTION_ROLE_ARN`.
Neither definition may set `repositoryCredentials`, `credentialSpecs`, a
FireLens log router, static labels, a health-check command, exposed ports, or
interactive terminals; logging, when present, must use `awslogs` with no
`secretOptions`. This closes alternate secret-loading, executable, and ingress
channels.
The submitter role needs `ecs:DescribeTaskDefinition` with `Resource: "*"` in a
statement without the `ecs:cluster` condition used to scope `ecs:RunTask`.

## Just Recipes

Projects that use `just` can import reusable container and scraper CLI recipes:

```just
aws_batch_scraper_cli_dir := "etl"
aws_batch_scraper_cli := "gv-dashboard-etl"
aws_batch_scraper_cli_group := "courts"
aws_batch_scraper_dockerfile := "packages/etl/Dockerfile"
aws_batch_scraper_browser_freshness_script := "etl/src/etl/chrome_release.py"
aws_batch_scraper_required_sbom_packages := "python:playwright=1.62.0,deb:google-chrome-stable=151.0.7922.169-1,binary:node=24.18.1"
aws_batch_scraper_chrome_executable_sha256 := "sha256:..."
aws_batch_scraper_chrome_sandbox_scan_args := "--forbid-chrome-sandbox --forbid-setuid-setgid-files"
aws_batch_scraper_release_evidence_root := ".artifacts/aws-batch-scraper/releases"

import "packages/aws-batch-scraper/just/aws-batch-scraper.just"
```

This project's release recipes require the final image to omit Chrome's
setuid sandbox helper and every other setuid/setgid file. The local SBOM gate
fails if `/opt/google/chrome/chrome-sandbox` or any privileged-mode file is
present; the worker instead relies on the reviewed Fargate task boundary and
the browser launch policy documented by the application.

The release recipes read `AWS_ACCOUNT_ID`, `AWS_REGION`,
`ECR_REPOSITORY_NAME`, `SCRAPER_IMAGE_TAG`, and optional `AWS_PROFILE`
directly from the environment. This keeps untrusted environment text out of
Just's generated shell source.

This adds generic recipes such as `scraper-build-container`,
`scraper-scan-container`, `scraper-push-container`, `scraper-submit`, `scraper-monitor`, and
`scraper-bench`. Your project Justfile can wrap them with domain-specific names
such as `courts-submit` or `build-container`.

The build and push recipes require a completely clean checkout and
`SCRAPER_IMAGE_TAG` equal to the full current commit SHA. They reject an ECR tag
that already exists. The release build streams `git archive HEAD` directly into
BuildKit, so ignored or other working-tree-only files cannot enter the image.
It labels and re-checks the exact scanned image ID, runs the local
SBOM/vulnerability gate, pushes that image ID, and verifies the remote scan.
After those checks pass, the recipe prints the full digest URI to use in the ECS
task definition. Pull-request CI intentionally builds the checked-out workspace
instead: it must test the proposed patch and never publishes that CI image. The
repository must separately
enforce immutable ECR tags and scan-on-push:

```bash
SCRAPER_IMAGE_TAG=$(git rev-parse HEAD) just scraper-build-and-push-container
```

## Templates

- `examples/docker/Dockerfile.python`: pure Python or HTTP scrapers
- `examples/docker/Dockerfile.playwright`: browser scrapers using Playwright
- `examples/docker/Dockerfile.monorepo`: monorepos with local editable packages

The repository `packages/etl/Dockerfile` is the courts scraper implementation image. It
is useful as a monorepo + Playwright example, but it is not the framework image.
