from typing import Any

from pydantic import Field, computed_field
from pydantic.fields import FieldInfo
from pydantic_settings import EnvSettingsSource, PydanticBaseSettingsSource
from pydantic_settings.sources.providers.dotenv import DotEnvSettingsSource

from dashboard_utils.config import S3Config


class _CSVMixin:
    """Fallback to comma-splitting for list[str] fields.

    pydantic-settings tries json.loads() on complex types before validators run.
    This mixin catches that failure and splits on commas instead, so env vars like
    ``ECS_SUBNET_IDS=subnet-a,subnet-b`` work without requiring JSON array syntax.
    """

    def decode_complex_value(self, field_name: str, field: FieldInfo, value: Any) -> Any:
        try:
            return super().decode_complex_value(field_name, field, value)  # type: ignore[misc]
        except Exception:
            if isinstance(value, str):
                return [v.strip() for v in value.split(",") if v.strip()]
            raise


class _CSVEnvSource(_CSVMixin, EnvSettingsSource):
    pass


class _CSVDotEnvSource(_CSVMixin, DotEnvSettingsSource):
    pass


class ScraperConfig(S3Config):
    """Settings for the submitter (local + GitHub Actions) and the Fargate worker.

    Both need SQS; the submitter additionally needs ECS settings to launch tasks.
    """

    # Strip FLY_* aliases — scraper uses AWS_PROFILE or task role, never Fly credentials
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    # Required for constructing SQS URLs and ECS ARNs (not needed by the API)
    aws_account_id: str = Field(..., description="AWS account ID, e.g. '985454606291'")

    # Queue names — derive URLs from these + account_id + region
    sqs_queue_name: str = "ujs-incidents"
    sqs_dlq_name: str = "ujs-incidents-dlq"

    # ECS — fixed names by convention, override via env if needed
    ecs_cluster_name: str = "ujs-scraper"
    ecs_task_definition: str = "ujs-scraper"
    ecs_container_name: str = "ujs-scraper"
    ecs_task_count: int = 9

    # ECS networking — accept comma-separated strings (e.g. subnet-a,subnet-b)
    ecs_subnet_ids: list[str]
    ecs_security_group_ids: list[str]

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type["ScraperConfig"],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        **kwargs: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            _CSVEnvSource(settings_cls),
            _CSVDotEnvSource(settings_cls),
            *kwargs.values(),
        )

    @computed_field
    @property
    def sqs_queue_url(self) -> str:
        return (
            f"https://sqs.{self.aws_region}.amazonaws.com"
            f"/{self.aws_account_id}/{self.sqs_queue_name}"
        )

    @computed_field
    @property
    def sqs_dlq_url(self) -> str:
        return (
            f"https://sqs.{self.aws_region}.amazonaws.com/{self.aws_account_id}/{self.sqs_dlq_name}"
        )

    @computed_field
    @property
    def ecs_cluster_arn(self) -> str:
        return (
            f"arn:aws:ecs:{self.aws_region}:{self.aws_account_id}:cluster/{self.ecs_cluster_name}"
        )
