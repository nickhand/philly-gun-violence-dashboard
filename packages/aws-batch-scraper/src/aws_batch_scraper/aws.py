"""Small AWS client/session helpers for the scraper framework."""

import os

import boto3

from aws_batch_scraper.config import ScraperBaseConfig


def make_boto3_session(
    *,
    config: ScraperBaseConfig | None = None,
    region_name: str | None = None,
) -> boto3.Session:
    """Create a boto3 session from env/profile/runtime credentials."""
    resolved_region = (
        region_name
        or (config.aws_region if config is not None else None)
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1"
    )
    session = boto3.Session(
        aws_access_key_id=(
            config.aws_access_key_id if config is not None else os.getenv("AWS_ACCESS_KEY_ID")
        ),
        aws_secret_access_key=(
            config.aws_secret_access_key
            if config is not None
            else os.getenv("AWS_SECRET_ACCESS_KEY")
        ),
        profile_name=config.aws_profile if config is not None else os.getenv("AWS_PROFILE"),
        region_name=resolved_region,
    )
    if not session.region_name:
        raise RuntimeError(
            "AWS region is not configured. Set AWS_REGION/AWS_DEFAULT_REGION "
            "or configure a default region in your AWS profile."
        )
    return session
