import os
from typing import TYPE_CHECKING, Final, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from pyproj import CRS

if TYPE_CHECKING:
    from types_boto3_s3.literals import BucketLocationConstraintType
else:
    BucketLocationConstraintType = str


def _env_file() -> str | None:
    # Only load .env locally so ECS doesn't care if it's missing.
    # In ECS, set ENV=prod (or anything not "local").
    return ".env" if os.getenv("ENV", "local") == "local" else None


class ETLConfig(BaseSettings):
    """Shared ETL environment variables.

    Attributes
    ----------
    REFERENCE_CRS : CRS
        The reference coordinate reference system (CRS) used for geospatial data.
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
        env_file=_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Pennsylvania State Plane South (NAD83)
    REFERENCE_CRS: Final[CRS] = CRS.from_epsg(2272)

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


settings = ETLConfig()
