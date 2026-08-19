"""Fail-closed release checks for immutable scraper container images."""

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

FULL_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IMAGE_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
AWS_ACCOUNT_ID_PATTERN = re.compile(r"^[0-9]{12}$")
ECR_REPOSITORY_PATTERN = re.compile(r"^(?=.{2,256}$)[a-z0-9]+(?:[._/-][a-z0-9]+)*$")
AWS_REGION_PATTERN = re.compile(r"^[a-z]{2}(?:-[a-z0-9]+)+-[0-9]+$")
REVISION_LABEL = "org.opencontainers.image.revision"

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class ReleaseIntegrityError(RuntimeError):
    """Raised when an image cannot be proven safe to publish."""


@dataclass(frozen=True, slots=True)
class ReleaseTarget:
    """One exact ECR repository and immutable commit tag."""

    account_id: str
    repository: str
    region: str
    tag: str
    profile: str | None = None

    def __post_init__(self) -> None:
        if AWS_ACCOUNT_ID_PATTERN.fullmatch(self.account_id) is None:
            raise ValueError("AWS account id must contain exactly 12 digits")
        if ECR_REPOSITORY_PATTERN.fullmatch(self.repository) is None:
            raise ValueError("ECR repository name is invalid")
        if AWS_REGION_PATTERN.fullmatch(self.region) is None:
            raise ValueError("AWS region is invalid")
        if FULL_COMMIT_PATTERN.fullmatch(self.tag) is None:
            raise ValueError("SCRAPER_IMAGE_TAG must be a full lowercase 40-character commit SHA")
        if self.profile is not None and (
            not self.profile.strip() or any(character.isspace() for character in self.profile)
        ):
            raise ValueError("AWS profile must be a non-blank token when provided")

    def aws_command(self, *arguments: str) -> list[str]:
        """Build an AWS CLI command without interpolating shell text."""
        command = ["aws"]
        if self.profile is not None:
            command.extend(("--profile", self.profile))
        command.extend(("--region", self.region, *arguments))
        return command

    @property
    def repository_uri(self) -> str:
        """Return the only ECR repository URI this release may target."""
        return f"{self.account_id}.dkr.ecr.{self.region}.amazonaws.com/{self.repository}"


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        list(command),
        check=False,
        capture_output=True,
        text=True,
    )


def _checked_output(
    runner: CommandRunner,
    command: Sequence[str],
    *,
    label: str,
) -> str:
    result = runner(command)
    if result.returncode != 0:
        raise ReleaseIntegrityError(f"{label} command failed")
    return result.stdout


def _json_output(
    runner: CommandRunner,
    command: Sequence[str],
    *,
    label: str,
) -> dict[str, Any]:
    output = _checked_output(runner, command, label=label)
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ReleaseIntegrityError(f"{label} returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise ReleaseIntegrityError(f"{label} did not return a JSON object")
    return value


def validate_release_source(
    tag: str,
    *,
    runner: CommandRunner = _default_runner,
) -> str:
    """Require the exact full HEAD commit and a clean tracked/untracked tree."""
    head = _checked_output(
        runner,
        ["git", "rev-parse", "--verify", "HEAD"],
        label="Git revision inspection",
    ).strip()
    if FULL_COMMIT_PATTERN.fullmatch(head) is None:
        raise ReleaseIntegrityError("Git HEAD is not a full lowercase 40-character commit SHA")
    if tag != head:
        raise ReleaseIntegrityError("SCRAPER_IMAGE_TAG must exactly equal the full Git HEAD SHA")

    status = _checked_output(
        runner,
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        label="Git worktree inspection",
    )
    if status.strip():
        raise ReleaseIntegrityError(
            "Scraper release images must be built from a completely clean checkout"
        )
    return head


def require_remote_tag_absent(
    target: ReleaseTarget,
    *,
    runner: CommandRunner = _default_runner,
) -> None:
    """Reject an ECR tag that already names any remote image."""
    payload = _json_output(
        runner,
        target.aws_command(
            "ecr",
            "list-images",
            "--registry-id",
            target.account_id,
            "--repository-name",
            target.repository,
            "--filter",
            "tagStatus=TAGGED",
            "--output",
            "json",
        ),
        label="ECR tag inspection",
    )
    image_ids = payload.get("imageIds")
    if not isinstance(image_ids, list):
        raise ReleaseIntegrityError("ECR tag inspection omitted imageIds")
    for image_id in image_ids:
        if not isinstance(image_id, dict):
            raise ReleaseIntegrityError("ECR tag inspection returned an invalid image ID")
        remote_tag = image_id.get("imageTag")
        if remote_tag is not None and not isinstance(remote_tag, str):
            raise ReleaseIntegrityError("ECR tag inspection returned a non-string tag")
        if remote_tag == target.tag:
            raise ReleaseIntegrityError(f"ECR tag {target.tag} already exists and is immutable")


def require_immutable_repository(
    target: ReleaseTarget,
    *,
    runner: CommandRunner = _default_runner,
) -> None:
    """Require ECR itself to close the absent-tag check/push race."""
    payload = _json_output(
        runner,
        target.aws_command(
            "ecr",
            "describe-repositories",
            "--registry-id",
            target.account_id,
            "--repository-names",
            target.repository,
            "--output",
            "json",
        ),
        label="ECR repository policy inspection",
    )
    repositories = payload.get("repositories")
    if (
        not isinstance(repositories, list)
        or len(repositories) != 1
        or not isinstance(repositories[0], dict)
    ):
        raise ReleaseIntegrityError("ECR policy inspection did not return one repository")
    repository = repositories[0]
    if repository.get("registryId") != target.account_id:
        raise ReleaseIntegrityError("ECR policy inspection returned the wrong registry account")
    if repository.get("repositoryName") != target.repository:
        raise ReleaseIntegrityError("ECR policy inspection returned the wrong repository")
    if repository.get("repositoryUri") != target.repository_uri:
        raise ReleaseIntegrityError("ECR policy inspection returned the wrong repository URI")
    if repository.get("imageTagMutability") != "IMMUTABLE":
        raise ReleaseIntegrityError(
            "ECR repository must enforce exact IMMUTABLE tag mutability before release"
        )
    scanning = repository.get("imageScanningConfiguration")
    if not isinstance(scanning, dict) or scanning.get("scanOnPush") is not True:
        raise ReleaseIntegrityError("ECR repository must enable scan-on-push before release")


def preflight_release(
    target: ReleaseTarget,
    *,
    runner: CommandRunner = _default_runner,
) -> None:
    """Validate source identity and remote tag absence before build or push."""
    validate_release_source(target.tag, runner=runner)
    require_immutable_repository(target, runner=runner)
    require_remote_tag_absent(target, runner=runner)


def verify_local_image(
    image: str,
    tag: str,
    *,
    runner: CommandRunner = _default_runner,
) -> None:
    """Require the locally built image to carry the expected commit label."""
    if not image.strip() or any(character.isspace() for character in image):
        raise ValueError("Local image name must be a non-blank token")
    if FULL_COMMIT_PATTERN.fullmatch(tag) is None:
        raise ValueError("Image revision must be a full lowercase 40-character commit SHA")
    output = _checked_output(
        runner,
        ["docker", "image", "inspect", "--format", "{{json .Config.Labels}}", image],
        label="Local image inspection",
    )
    try:
        labels = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ReleaseIntegrityError("Local image labels were malformed") from exc
    if not isinstance(labels, dict) or labels.get(REVISION_LABEL) != tag:
        raise ReleaseIntegrityError(f"Local image must carry {REVISION_LABEL}={tag}")


def _resolve_remote_digest(
    target: ReleaseTarget,
    *,
    runner: CommandRunner,
) -> str:
    payload = _json_output(
        runner,
        target.aws_command(
            "ecr",
            "describe-images",
            "--registry-id",
            target.account_id,
            "--repository-name",
            target.repository,
            "--image-ids",
            f"imageTag={target.tag}",
            "--output",
            "json",
        ),
        label="ECR digest resolution",
    )
    details = payload.get("imageDetails")
    if not isinstance(details, list) or len(details) != 1 or not isinstance(details[0], dict):
        raise ReleaseIntegrityError("ECR digest resolution did not return one exact image")
    detail = details[0]
    if detail.get("registryId") != target.account_id:
        raise ReleaseIntegrityError("ECR digest resolution returned the wrong registry account")
    if detail.get("repositoryName") != target.repository:
        raise ReleaseIntegrityError("ECR digest resolution returned the wrong repository")
    digest = detail.get("imageDigest")
    tags = detail.get("imageTags")
    if not isinstance(digest, str) or IMAGE_DIGEST_PATTERN.fullmatch(digest) is None:
        raise ReleaseIntegrityError("ECR returned an invalid image digest")
    if not isinstance(tags, list) or target.tag not in tags:
        raise ReleaseIntegrityError("Resolved ECR image no longer carries the requested tag")
    return digest


def verify_remote_scan(
    target: ReleaseTarget,
    *,
    runner: CommandRunner = _default_runner,
) -> str:
    """Resolve the pushed digest, wait for its scan, and reject severe findings."""
    digest = _resolve_remote_digest(target, runner=runner)
    image_id = f"imageDigest={digest}"
    _checked_output(
        runner,
        target.aws_command(
            "ecr",
            "wait",
            "image-scan-complete",
            "--registry-id",
            target.account_id,
            "--repository-name",
            target.repository,
            "--image-id",
            image_id,
        ),
        label="ECR image scan waiter",
    )
    payload = _json_output(
        runner,
        target.aws_command(
            "ecr",
            "describe-image-scan-findings",
            "--registry-id",
            target.account_id,
            "--repository-name",
            target.repository,
            "--image-id",
            image_id,
            "--output",
            "json",
        ),
        label="ECR image scan findings",
    )
    response_image_id = payload.get("imageId")
    if payload.get("registryId") != target.account_id:
        raise ReleaseIntegrityError("ECR scan findings returned the wrong registry account")
    if payload.get("repositoryName") != target.repository:
        raise ReleaseIntegrityError("ECR scan findings returned the wrong repository")
    if not isinstance(response_image_id, dict) or response_image_id.get("imageDigest") != digest:
        raise ReleaseIntegrityError("ECR scan findings did not match the pushed image digest")
    status = payload.get("imageScanStatus")
    if not isinstance(status, dict) or status.get("status") != "COMPLETE":
        raise ReleaseIntegrityError("ECR image scan did not reach COMPLETE")
    findings = payload.get("imageScanFindings")
    if not isinstance(findings, dict):
        raise ReleaseIntegrityError("ECR image scan omitted its findings")
    counts = findings.get("findingSeverityCounts", {})
    if not isinstance(counts, dict):
        raise ReleaseIntegrityError("ECR image scan returned invalid severity counts")
    normalized_counts: dict[str, int] = {}
    for severity, count in counts.items():
        if not isinstance(severity, str) or isinstance(count, bool) or not isinstance(count, int):
            raise ReleaseIntegrityError("ECR image scan returned an invalid severity count")
        if count < 0:
            raise ReleaseIntegrityError("ECR image scan returned a negative severity count")
        normalized_counts[severity.upper()] = count
    critical = normalized_counts.get("CRITICAL", 0)
    high = normalized_counts.get("HIGH", 0)
    if critical or high:
        raise ReleaseIntegrityError(
            f"ECR scan blocked release: {critical} Critical and {high} High findings"
        )
    return digest


def _target_from_args(args: argparse.Namespace) -> ReleaseTarget:
    profile = args.profile.strip() if args.profile else None
    return ReleaseTarget(
        account_id=args.account_id,
        repository=args.repository,
        region=args.region,
        tag=args.tag,
        profile=profile,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_target_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--account-id", required=True)
        command.add_argument("--repository", required=True)
        command.add_argument("--region", required=True)
        command.add_argument("--tag", required=True)
        command.add_argument("--profile")

    preflight = subparsers.add_parser("preflight")
    add_target_arguments(preflight)

    local = subparsers.add_parser("verify-local-image")
    local.add_argument("--image", required=True)
    local.add_argument("--tag", required=True)

    scan = subparsers.add_parser("verify-scan")
    add_target_arguments(scan)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one release-integrity command."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            preflight_release(_target_from_args(args))
        elif args.command == "verify-local-image":
            verify_local_image(args.image, args.tag)
        elif args.command == "verify-scan":
            print(verify_remote_scan(_target_from_args(args)))
        else:  # pragma: no cover - argparse constrains this state.
            raise AssertionError(f"Unhandled release command: {args.command}")
    except (ReleaseIntegrityError, ValueError) as exc:
        print(f"Release integrity check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
