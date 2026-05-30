from dashboard_utils.config import S3Config


class APIConfig(S3Config):
    """Settings for the FastAPI app deployed to Fly.

    Only reads from the processed prefix. Inherits the other prefix names
    from ``S3Config`` for consistency, but doesn't use them.
    """

    # API refresh configuration
    # Lazy-refresh TTL for API caches (in seconds).
    api_refresh_ttl_seconds: int = 300


settings = APIConfig()
