"""Scan the immutable image selected for production, using that release's Chrome lock."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import boto3
from aws_batch_scraper.release_image import (
    IMAGE_DIGEST_PATTERN,
    PackageRequirement,
    ReleaseTarget,
    scan_deployed_image,
)

from etl.chrome_release import load_chrome_lock
from etl.courts.deployment import CourtsRelease, lock_digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("observation", type=Path)
    args = parser.parse_args()
    bucket = os.environ["S3_BUCKET"]
    key = os.environ["COURTS_RELEASE_KEY"]
    if key != "ujs-scraper/deployment/active.json":
        raise ValueError("Expected the active courts release pointer")
    region = os.environ["AWS_REGION"]
    s3 = boto3.client("s3", region_name=region)
    pointer = s3.get_object(Bucket=bucket, Key=key)
    with pointer["Body"] as stream:
        data = stream.read(16385)
    etag = pointer.get("ETag")
    if not isinstance(etag, str) or not etag or len(data) > 16384:
        raise ValueError("Invalid active release pointer or missing ETag")
    release = CourtsRelease.model_validate_json(data)
    target = ReleaseTarget(os.environ["AWS_ACCOUNT_ID"], "ujs-scraper", region, release.source_sha)
    repository, separator, digest = release.image.partition("@")
    if (
        not separator
        or repository != target.repository_uri
        or not IMAGE_DIGEST_PATTERN.fullmatch(digest)
    ):
        raise ValueError("The active release must name the production ECR repository by digest")

    # Read historical pins as data. Execute only the monitor from the trusted checkout.
    contents = subprocess.check_output(
        ["git", "show", f"{release.source_sha}:packages/etl/chrome-lock.json"]
    )
    if lock_digest(contents) != release.chrome_lock_sha256:
        raise ValueError(
            "The Chrome lock at the deployed source SHA differs from the release pointer"
        )
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory, "chrome-lock.json")
        path.write_bytes(contents)
        lock = load_chrome_lock(path)
    observation = scan_deployed_image(
        target,
        digest,
        requirements=[PackageRequirement("deb", lock.package.name, lock.package.version)],
        expected_distro_name="ubuntu",
        expected_distro_version="26.04",
        expected_chrome_executable_sha256=f"sha256:{lock.executable.sha256}",
        output_directory=args.evidence,
    )
    # If another release won promotion during scanning, preserve diagnostics only.
    s3.head_object(Bucket=bucket, Key=key, IfMatch=etag)
    observation["observed_at"] = datetime.now(UTC).isoformat()
    with args.observation.open("x") as stream:
        stream.write(json.dumps(observation, indent=2) + "\n")
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as stream:
        stream.write(
            f"Scanned `{release.image}` (Chrome {lock.package.product_version}). "
            f"Found {len(observation['findings'])} release-blocking matches. "
            f"The stored ECR result is from `{observation['ecr']['scan_completed_at']}`.\n"
        )


if __name__ == "__main__":
    main()
