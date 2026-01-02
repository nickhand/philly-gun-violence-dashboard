import os
from pathlib import Path
from typing import Literal

from mypy_boto3_s3.literals import BucketLocationConstraintType
from pydantic_settings import BaseSettings, SettingsConfigDict


def is_prod_runtime() -> bool:
    """Check if the current runtime environment is production.

    Returns
    -------
    bool
        True if the environment variable 'ENV' is set to 'prod', False otherwise.
    """
    return os.getenv("ENV", "local") == "prod"


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
        return str(get_repo_root() / ".env")
    else:
        return None


class AWSConfig(BaseSettings):
    """Shared AWS environment variables.

    Attributes
    ----------
    AWS_ACCESS_KEY_ID : str
        AWS access key ID for accessing AWS services.
    AWS_SECRET_ACCESS_KEY : str
        AWS secret access key for accessing AWS services.
    AWS_REGION : "us-east-1" | BucketLocationConstraintType
        The AWS region where the services are hosted.
    AWS_BUCKET_NAME : str
        The name of the AWS S3 bucket used for storing data.
    AWS_ACCOUNT_ID : str
        The AWS account ID associated with the services.
    CONTAINER_NAME : str
        The name of the container used in AWS ECR.
    ECS_CLUSTER_NAME : str
        The name of the ECS cluster used for running batch jobs.
    """

    model_config = SettingsConfigDict(
        env_file=get_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # AWS credentials
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None

    # AWS S3 Configurations
    AWS_REGION: Literal["us-east-1"] | BucketLocationConstraintType = "us-east-1"
    AWS_BUCKET_NAME: str

    # ECR/ECS Configurations
    AWS_ACCOUNT_ID: str
    CONTAINER_NAME: str
    ECS_CLUSTER_NAME: str


settings = AWSConfig()
