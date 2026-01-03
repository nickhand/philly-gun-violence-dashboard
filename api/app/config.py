from pydantic_settings import SettingsConfigDict

from dashboard_utils.env import S3Config, get_env_file


class APIConfig(S3Config):
    """Shared application configuration settings.

    Attributes
    ----------
    AWS_BUCKET_NAME : str
        Name of the S3 bucket used for storing application data.
    """

    model_config = SettingsConfigDict(
        env_file=get_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API refresh configuration
    # Lazy-refresh TTL for API caches (in seconds).
    API_REFRESH_TTL_SECONDS: int = 300


settings = APIConfig()
