"""Atomic, validated production pins for the courts ECS release."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Literal

from aws_batch_scraper.orchestrate import resolve_split_task_definitions
from pydantic import BaseModel, ConfigDict, Field

from etl.courts.config import CourtsSubmitterConfig

PIN_NAMES = ("ECS_TASK_DEFINITION", "ECS_MONITOR_TASK_DEFINITION", "ECS_EXPECTED_IMAGE_URI")


class CourtsRelease(BaseModel):
    """One indivisible worker/monitor/image generation, with its source identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[1] = 1
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    chrome_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    worker: str
    monitor: str
    image: str

    def pins(self) -> dict[str, str]:
        return dict(zip(PIN_NAMES, (self.worker, self.monitor, self.image), strict=True))

    def config(self) -> CourtsSubmitterConfig:
        # Use normal settings validation; never bypass it with model_copy(update=...).
        return CourtsSubmitterConfig(
            ecs_task_definition=self.worker,
            ecs_monitor_task_definition=self.monitor,
            ecs_expected_image_uri=self.image,
        )


def lock_digest(content: bytes) -> str:
    """Hash canonical JSON so formatting alone does not redeploy Chrome."""
    return hashlib.sha256(
        json.dumps(json.loads(content), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_release(s3: Any, config: CourtsSubmitterConfig, key: str) -> tuple[CourtsRelease, str]:
    if key != f"{config.s3_scraper_prefix}/deployment/active.json":
        raise ValueError("COURTS_RELEASE_KEY must be the reviewed deployment pointer")
    response = s3.get_object(Bucket=config.s3_bucket, Key=key)
    etag = response.get("ETag")
    if not isinstance(etag, str) or not etag:
        raise ValueError("Deployment pointer has no ETag")
    return CourtsRelease.model_validate_json(response["Body"].read(16385)), etag


def load_release_environment(s3: Any, ecs: Any) -> dict[str, str]:
    """Resolve pins once at submission, requiring a valid pointer when enabled."""
    key = os.environ.get("COURTS_RELEASE_KEY", "")
    if not key:
        return {}  # Migration only: the existing exact repository pins remain valid.
    release, _ = read_release(s3, CourtsSubmitterConfig(), key)
    resolve_split_task_definitions(ecs, release.config())
    return release.pins()
