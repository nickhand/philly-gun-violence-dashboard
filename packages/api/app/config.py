from pydantic import Field

from dashboard_utils.config import S3Config


class APIConfig(S3Config):
    """Settings for the FastAPI app deployed to Fly.

    Reads processed datasets, geographic references, and the stable public
    download manifest that also serves as the shootings release pointer.
    """

    # API refresh configuration
    # Lazy-refresh TTL for API caches (in seconds).
    api_refresh_ttl_seconds: int = Field(default=300, ge=0)
    # Briefly back off after a failed refresh so an S3 outage cannot make every
    # incoming request repeat the same remote I/O. The complete stale snapshot
    # remains available throughout the backoff.
    api_refresh_failure_backoff_seconds: int = Field(default=30, ge=1)
    # Readiness fails when either daily source has not advanced for this many
    # days. Liveness remains independent so Fly can restart only dead processes.
    api_readiness_max_data_age_days: int = Field(default=14, ge=1)
    # Comma-separated exact browser origins added by a deployed canary. The
    # canonical site and local development origins remain available by default.
    api_cors_origins: str = ""


settings = APIConfig()
