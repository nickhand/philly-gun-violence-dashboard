from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import NoDecode

from dashboard_utils.config import S3Config


class WorkerConfig(S3Config):
    """Settings for the Fargate worker: S3 + SQS only.

    Does not include ECS fields — workers never launch other tasks.
    Also used by aggregate, stats, and process commands that only need S3/SQS.
    """

    # Required for constructing SQS URLs
    aws_account_id: str = Field(..., description="AWS account ID, e.g. '985454606291'")

    # Queue names — derive URLs from these + account_id + region
    sqs_queue_name: str = "ujs-incidents"
    sqs_dlq_name: str = "ujs-incidents-dlq"
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
    """

    # ECS — fixed names by convention, override via env if needed
    ecs_cluster_name: str = "ujs-scraper"
    ecs_task_definition: str = "ujs-scraper"
    ecs_container_name: str = "ujs-scraper"
    ecs_task_count: int = 9

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
