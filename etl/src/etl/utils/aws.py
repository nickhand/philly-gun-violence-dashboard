"""Utility functions for AWS interactions."""

from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache
from io import TextIOWrapper
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, cast

import boto3
from botocore.exceptions import ClientError
from loguru import logger

from etl.config import settings
from etl.utils.paths import data_dir

if TYPE_CHECKING:
    from types_boto3_s3.client import S3Client
else:
    S3Client = object  # type: ignore


def get_session() -> boto3.Session:
    """Make a boto3 Session from the given ETLConfig.

    Only include the access key and secret if they are set.
    """
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        return boto3.Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
    else:
        return boto3.Session(region_name=settings.AWS_REGION)


@lru_cache(maxsize=1)
def get_s3_client() -> S3Client:
    session = get_session()
    return session.client("s3")


def ensure_bucket(bucket: str, client: S3Client | None = None) -> None:
    """Ensure the given S3 bucket exists (create if missing).

    Parameters
    ----------
    bucket : str
        The name of the S3 bucket to ensure.
    client : S3Client | None, optional
        An optional S3 client to use. If None, a new client will be created.
    """
    if client is None:
        client = get_s3_client()
    _ensure_bucket(client, bucket)


def _ensure_bucket(client: S3Client, bucket: str) -> None:
    """Ensure the given S3 bucket exists (create if missing)."""
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")

        # Create the bucket if it does not exist
        if error_code in ("404", 404, "NoSuchBucket"):
            logger.info(f"Creating S3 bucket {bucket}")

            # We need to specify the region unless it's us-east-1
            if settings.AWS_REGION != "us-east-1":
                client.create_bucket(
                    Bucket=bucket,
                    CreateBucketConfiguration={"LocationConstraint": settings.AWS_REGION},
                )
            else:
                client.create_bucket(Bucket=bucket)
        else:
            raise


def mirror_to_s3(local_path: Path) -> None:
    """Upload a single local file to S3, preserving its path relative to data/.

    Parameters
    ----------
    local_path : Path
        The full local path to the file to upload.
    """
    if not local_path.exists():
        raise FileNotFoundError(f"Local file does not exist: {local_path}")

    root = data_dir()
    try:
        rel = local_path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path {local_path} is not under data_dir()") from exc

    dest = rel.as_posix()
    bucket_name = settings.AWS_BUCKET_NAME

    client = get_s3_client()
    _ensure_bucket(client, bucket_name)

    logger.info(f"Uploading {local_path} -> s3://{bucket_name}/{dest}")
    client.upload_file(local_path.as_posix(), bucket_name, dest)


@contextmanager
def open_csv_from_s3(s3_client: S3Client, *, bucket: str, key: str) -> Generator[TextIOWrapper]:
    """Open a CSV file from S3 and yield a binary file-like object.

    Parameters
    ----------
    s3_client : S3Client
        Boto3 S3 client.
    bucket : str
        S3 bucket name.
    key : str
        S3 object key.

    Yields
    ------
    binary file-like object
        A binary file-like object for the CSV data.
    """
    # Get the echoed input CSV
    input_obj = s3_client.get_object(Bucket=bucket, Key=key)
    body = cast(BinaryIO, input_obj["Body"])  # StreamingBody is binary-ish at runtime

    f = TextIOWrapper(body, encoding="utf-8")
    yield f
    f.close()
