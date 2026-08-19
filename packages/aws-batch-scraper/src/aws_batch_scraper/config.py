"""Configuration classes for the aws-batch-scraper framework."""

import os
import re
from pathlib import Path
from typing import Annotated, Self

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_TASK_DEFINITION_FAMILY_REVISION = re.compile(r"^[A-Za-z0-9_-]{1,255}:[1-9][0-9]*$")
_TASK_DEFINITION_ARN_REVISION = re.compile(
    r"^arn:[^:]+:ecs:[^:]+:[0-9]{12}:task-definition/"
    r"[A-Za-z0-9_-]{1,255}:[1-9][0-9]*$"
)
_GITHUB_REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
_GITHUB_WORKFLOW_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\.ya?ml$")
_SUBNET_ID = re.compile(r"^subnet-[A-Za-z0-9]+$")
_SECURITY_GROUP_ID = re.compile(r"^sg-[A-Za-z0-9]+$")
_ECR_IMAGE_URI = re.compile(
    r"^(?P<account>[0-9]{12})\.dkr\.ecr\.(?P<region>[a-z]{2}(?:-[a-z0-9]+)+-[0-9]+)"
    r"\.amazonaws\.com(?:\.cn)?/(?P<repository>"
    r"[a-z0-9]+(?:[._/-][a-z0-9]+)*)@sha256:[0-9a-f]{64}$"
)


def require_exact_task_definition(
    value: str,
    *,
    setting_name: str = "ECS_TASK_DEFINITION",
) -> str:
    """Return an exact ECS task-definition revision or raise actionable error."""
    if isinstance(value, str) and (
        _TASK_DEFINITION_FAMILY_REVISION.fullmatch(value)
        or _TASK_DEFINITION_ARN_REVISION.fullmatch(value)
    ):
        return value
    raise ValueError(
        f"{setting_name} must be an exact family:revision or revisioned "
        "task-definition ARN backed by an immutable image digest; bare families "
        "silently select the mutable latest revision"
    )


def _task_definition_identity(value: str) -> str:
    """Normalize short and ARN spellings so one revision cannot fill both roles."""
    return value.rsplit("task-definition/", maxsplit=1)[-1]


def require_split_task_definitions(worker: str, monitor: str) -> tuple[str, str]:
    """Validate distinct, immutable worker and monitor task-definition revisions."""
    exact_worker = require_exact_task_definition(worker)
    exact_monitor = require_exact_task_definition(
        monitor,
        setting_name="ECS_MONITOR_TASK_DEFINITION",
    )
    if _task_definition_identity(exact_worker) == _task_definition_identity(exact_monitor):
        raise ValueError(
            "ECS_TASK_DEFINITION and ECS_MONITOR_TASK_DEFINITION must identify "
            "different task-definition revisions; sharing a definition can expose "
            "monitor-only credentials to workers"
        )
    return exact_worker, exact_monitor


def require_exact_ecr_image_uri(
    value: str | None,
    *,
    account_id: str,
    region: str,
) -> str:
    """Require the exact scanned ECR image selected for both task revisions."""
    match = _ECR_IMAGE_URI.fullmatch(value) if isinstance(value, str) else None
    if match is None or match.group("account") != account_id or match.group("region") != region:
        raise ValueError(
            "ECS_EXPECTED_IMAGE_URI must be an exact same-account, same-region "
            "ECR repository@sha256 digest produced by the release gate"
        )
    return match.string


def require_github_repository(value: str | None) -> str:
    """Require the explicit owner/repository target used for terminal dispatch."""
    if isinstance(value, str) and _GITHUB_REPOSITORY.fullmatch(value):
        _, repository = value.split("/", maxsplit=1)
        if repository not in {".", ".."}:
            return value
    raise ValueError("GITHUB_REPOSITORY must be an explicit owner/repository value")


def require_github_workflow_file(value: str | None) -> str:
    """Require a workflow filename rather than an arbitrary API path."""
    if isinstance(value, str) and _GITHUB_WORKFLOW_FILE.fullmatch(value):
        return value
    raise ValueError("GITHUB_WORKFLOW_FILE must be an explicit .yml or .yaml workflow filename")


def _env_file() -> str | None:
    """Find a repository .env file for local runs; avoid filesystem lookup in ECS."""
    if os.getenv("ENV", "dev") == "prod":
        return None

    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    for base in candidates:
        env_path = base / ".env"
        if env_path.exists():
            return str(env_path)
    return None


class ScraperBaseConfig(BaseSettings):
    """Minimal AWS/S3 settings needed by the scraper framework."""

    model_config = SettingsConfigDict(
        env_file=_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    aws_account_id: str | None = None
    aws_profile: str | None = None
    aws_region: str = "us-east-1"
    s3_bucket: str = Field(
        ...,
        validation_alias=AliasChoices("s3_bucket", "aws_bucket_name"),
        description="S3 bucket name",
    )
    s3_scraper_prefix: str = Field(..., description="S3 prefix for scraper results")


class WorkerConfig(ScraperBaseConfig):
    """Settings for the Fargate worker: S3 + SQS only.

    Does not include ECS fields — workers never launch other tasks.
    Also used by aggregate, stats, and process commands that only need S3/SQS.

    Subclass this to add plugin-specific defaults (queue names, prefixes, etc.).
    """

    # Required in the framework; subclasses should provide defaults
    aws_account_id: str = Field(..., description="AWS account ID, e.g. '985454606291'")
    sqs_queue_name: str = Field(..., description="Main SQS queue name")
    sqs_dlq_name: str = Field(..., description="Dead-letter queue name")

    run_id: str = "unknown"
    # Retained for backwards-compatible task environments. Current workers
    # use the message-scoped force_rescrape field instead.
    force_rescrape: bool = False
    soft_blocked_delay_min: int = 300
    soft_blocked_delay_max: int = 900
    github_repository: str | None = None

    @property
    def sqs_queue_url(self) -> str:
        """Fully qualified SQS queue URL derived from account, region, and queue name."""
        return (
            f"https://sqs.{self.aws_region}.amazonaws.com"
            f"/{self.aws_account_id}/{self.sqs_queue_name}"
        )

    @property
    def sqs_dlq_url(self) -> str:
        """Fully qualified SQS dead-letter queue URL."""
        return (
            f"https://sqs.{self.aws_region}.amazonaws.com/{self.aws_account_id}/{self.sqs_dlq_name}"
        )


class SubmitterConfig(WorkerConfig):
    """Settings for the submitter and monitor: extends WorkerConfig with ECS fields.

    Used by the submit and monitor commands that need to launch and track Fargate tasks.

    Subclass this to add plugin-specific ECS defaults (cluster name, task definition, etc.).
    """

    ecs_cluster_name: str = Field(..., description="ECS cluster name")
    ecs_task_definition: str = Field(
        ...,
        description="Exact worker ECS family:revision or revisioned task-definition ARN",
    )
    ecs_monitor_task_definition: str = Field(
        ...,
        description="Exact monitor ECS family:revision or revisioned task-definition ARN",
    )
    ecs_expected_image_uri: str | None = Field(
        default=None,
        description="Exact ECR repository@sha256 URI approved by the release gate",
    )
    ecs_container_name: str = Field(..., description="ECS container name for overrides")
    ecs_task_count: int = Field(default=1, ge=1, le=10)
    github_workflow_file: str | None = None

    # ECS networking — accept comma-separated strings (e.g. subnet-a,subnet-b)
    ecs_subnet_ids: Annotated[list[str], NoDecode]
    ecs_security_group_ids: Annotated[list[str], NoDecode]

    @field_validator("ecs_subnet_ids", "ecs_security_group_ids", mode="before")
    @classmethod
    def _split_csv_list(cls, value: object) -> object:
        """Accept either JSON/list values or comma-separated env strings."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("ecs_subnet_ids")
    @classmethod
    def _valid_subnet_ids(cls, value: list[str]) -> list[str]:
        if not 1 <= len(value) <= 16:
            raise ValueError("ECS_SUBNET_IDS must contain between 1 and 16 subnet IDs")
        if len(set(value)) != len(value) or any(not _SUBNET_ID.fullmatch(item) for item in value):
            raise ValueError("ECS_SUBNET_IDS must contain unique subnet-* identifiers")
        return value

    @field_validator("ecs_security_group_ids")
    @classmethod
    def _valid_security_group_ids(cls, value: list[str]) -> list[str]:
        if not 1 <= len(value) <= 5:
            raise ValueError(
                "ECS_SECURITY_GROUP_IDS must contain between 1 and 5 security-group IDs"
            )
        if len(set(value)) != len(value) or any(
            not _SECURITY_GROUP_ID.fullmatch(item) for item in value
        ):
            raise ValueError("ECS_SECURITY_GROUP_IDS must contain unique sg-* identifiers")
        return value

    @field_validator("ecs_task_definition")
    @classmethod
    def _exact_task_definition(cls, value: str) -> str:
        return require_exact_task_definition(value)

    @field_validator("ecs_monitor_task_definition")
    @classmethod
    def _exact_monitor_task_definition(cls, value: str) -> str:
        return require_exact_task_definition(
            value,
            setting_name="ECS_MONITOR_TASK_DEFINITION",
        )

    @field_validator("github_repository")
    @classmethod
    def _valid_github_repository(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_github_repository(value)

    @field_validator("github_workflow_file")
    @classmethod
    def _valid_github_workflow_file(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_github_workflow_file(value)

    @model_validator(mode="after")
    def _split_task_definitions(self) -> Self:
        require_split_task_definitions(
            self.ecs_task_definition,
            self.ecs_monitor_task_definition,
        )
        if self.ecs_expected_image_uri is not None:
            require_exact_ecr_image_uri(
                self.ecs_expected_image_uri,
                account_id=self.aws_account_id,
                region=self.aws_region,
            )
        return self

    @property
    def ecs_cluster_arn(self) -> str:
        """Fully qualified ECS cluster ARN derived from account, region, and cluster name."""
        return (
            f"arn:aws:ecs:{self.aws_region}:{self.aws_account_id}:cluster/{self.ecs_cluster_name}"
        )
