"""Example scraper config defaults."""

from aws_batch_scraper.config import SubmitterConfig, WorkerConfig


class SimpleWorkerConfig(WorkerConfig):
    """Worker defaults for the example scraper."""

    sqs_queue_name: str = "simple-scraper"
    sqs_dlq_name: str = "simple-scraper-dlq"
    s3_scraper_prefix: str = "simple-scraper"


class SimpleSubmitterConfig(SimpleWorkerConfig, SubmitterConfig):
    """Submitter defaults for the example scraper."""

    ecs_cluster_name: str = "simple-scraper"
    ecs_task_definition: str = "simple-scraper:1"
    ecs_monitor_task_definition: str = "simple-scraper-monitor:1"
    ecs_container_name: str = "simple-scraper"
    ecs_task_count: int = 1
