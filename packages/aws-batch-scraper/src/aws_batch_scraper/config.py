"""Configuration classes for the aws-batch-scraper framework."""

import os
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
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
    ecs_task_definition: str = Field(..., description="ECS task definition name or ARN")
    ecs_container_name: str = Field(..., description="ECS container name for overrides")
    ecs_task_count: int = 1

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

    @property
    def ecs_cluster_arn(self) -> str:
        """Fully qualified ECS cluster ARN derived from account, region, and cluster name."""
        return (
            f"arn:aws:ecs:{self.aws_region}:{self.aws_account_id}:cluster/{self.ecs_cluster_name}"
        )
