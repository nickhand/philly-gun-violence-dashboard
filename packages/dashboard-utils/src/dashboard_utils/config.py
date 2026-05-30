import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from mypy_boto3_s3.literals import BucketLocationConstraintType
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def is_prod_runtime() -> bool:
    """Check if the current runtime environment is production.

    Returns
    -------
    bool
        True if the environment variable 'ENV' is set to 'prod', False otherwise.
    """
    return os.getenv("ENV", "dev") == "prod"


def get_repo_root() -> Path:
    """Find the root directory of the local cloned repository.

    This function crawls up the directory tree from the current file's location
    until it finds a directory containing a .git folder, which is assumed to be
    the root of the repository.
    """
    if is_prod_runtime():
        raise RuntimeError("Repository root lookup is not supported in production.")

    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / ".git").exists():
            return parent

    raise FileNotFoundError("Repository root not found.")


def get_env_file() -> str | None:
    """Get the appropriate .env file based on the runtime environment.

    Returns
    -------
    str | None
        Path to the .env file if in local environment, None if in production.
    """
    # Only load .env locally so ECS doesn't care if it's missing.
    # In ECS, set ENV=prod (or anything not "local").
    if not is_prod_runtime():
        try:
            return str(get_repo_root() / ".env")
        except FileNotFoundError:
            return None
    return None


class _Base(BaseSettings):
    """Shared pydantic-settings configuration for all settings classes."""

    model_config = SettingsConfigDict(
        env_file=get_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


class AWSConfig(_Base):
    """Base AWS settings consumed by boto3's credential chain.

    Credentials are resolved in priority order:
    1. ``aws_profile`` — developer laptops only; must be unset in ECS/Fly.
    2. boto3 credential chain (task role in ECS, env vars in CI).
    """

    aws_account_id: str | None = None
    aws_profile: str | None = None
    aws_region: Literal["us-east-1"] | BucketLocationConstraintType = "us-east-1"


class S3Config(AWSConfig):
    """S3 bucket and prefix names.

    The bucket is shared across components but each component touches only
    a subset of prefixes. IAM policies enforce the actual access boundary;
    these fields are just for constructing keys in code.
    """

    s3_bucket: str = Field(
        ...,
        validation_alias=AliasChoices("s3_bucket", "aws_bucket_name"),
        description="S3 bucket name, e.g. 'philly-gun-violence-dashboard'",
    )
    s3_scraper_prefix: str = "ujs-scraper"
    s3_processed_prefix: str = "processed"
    s3_reference_prefix: str = "reference"


@lru_cache
def get_aws_settings() -> AWSConfig:
    """Load AWS settings once per process."""
    return AWSConfig()


@lru_cache
def get_s3_settings() -> S3Config:
    """Load S3 settings once per process."""
    return S3Config()
