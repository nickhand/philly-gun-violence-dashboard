"""UJS courts scraper configuration with UJS-specific defaults."""

from aws_batch_scraper.config import SubmitterConfig, WorkerConfig


class CourtsWorkerConfig(WorkerConfig):
    """WorkerConfig with UJS-specific defaults.

    Environment variables map 1-to-1 with field names (case-insensitive).
    """

    sqs_queue_name: str = "ujs-incidents"
    sqs_dlq_name: str = "ujs-incidents-dlq"
    s3_scraper_prefix: str = "ujs-scraper"


class CourtsSubmitterConfig(CourtsWorkerConfig, SubmitterConfig):
    """SubmitterConfig with UJS-specific ECS defaults.

    MRO: CourtsSubmitterConfig → CourtsWorkerConfig → SubmitterConfig → WorkerConfig
    Inherits ECS field declarations and csv-list validator from SubmitterConfig.
    """

    ecs_cluster_name: str = "ujs-scraper"
    ecs_container_name: str = "ujs-scraper"
    ecs_task_count: int = 9
    github_workflow_file: str = "courts-process.yml"
