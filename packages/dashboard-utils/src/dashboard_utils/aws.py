import io
import json
from functools import lru_cache
from typing import Any

import boto3
import geopandas as gpd
import pandas as pd
from botocore.exceptions import ClientError
from mypy_boto3_s3.client import S3Client

from dashboard_utils.config import get_aws_settings


@lru_cache(maxsize=1)
def make_boto3_session(*, region_name: str | None = None) -> boto3.Session:
    """Create a boto3 session from dashboard AWS settings."""
    settings = get_aws_settings()
    session = boto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        profile_name=settings.aws_profile,
        region_name=region_name or str(settings.aws_region),
    )
    if not session.region_name:
        raise RuntimeError(
            "AWS region is not configured. Set AWS_REGION/AWS_DEFAULT_REGION "
            "or configure `region = ...` in your AWS profile (~/.aws/config)."
        )
    return session


@lru_cache(maxsize=1)
def make_s3_client(*, region_name: str | None = None) -> S3Client:
    """Create an S3 client from dashboard AWS settings."""
    return make_boto3_session(region_name=region_name).client("s3")


def _raise_if_not_found(err: ClientError, bucket: str, key: str) -> None:
    code = err.response.get("Error", {}).get("Code")
    if code in {"NoSuchKey", "404"}:
        raise FileNotFoundError(f"S3 object not found: s3://{bucket}/{key}") from err
    raise err


def read_bytes(s3: S3Client, bucket: str, key: str) -> bytes:
    """Read an S3 object as bytes."""
    try:
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as err:
        _raise_if_not_found(err, bucket, key)
        raise


def write_bytes(
    s3: S3Client,
    bucket: str,
    key: str,
    data: bytes,
    *,
    content_type: str | None = None,
) -> None:
    """Write bytes to S3."""
    if content_type:
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    else:
        s3.put_object(Bucket=bucket, Key=key, Body=data)


def read_text(s3: S3Client, bucket: str, key: str, *, encoding: str = "utf-8") -> str:
    """Read an S3 object as text."""
    return read_bytes(s3, bucket, key).decode(encoding)


def write_text(
    s3: S3Client,
    bucket: str,
    key: str,
    text: str,
    *,
    encoding: str = "utf-8",
    content_type: str | None = None,
) -> None:
    """Write text to S3."""
    write_bytes(s3, bucket, key, text.encode(encoding), content_type=content_type)


def read_json(s3: S3Client, bucket: str, key: str) -> Any:
    """Read JSON from S3."""
    return json.loads(read_text(s3, bucket, key))


def write_json(
    s3: S3Client,
    bucket: str,
    key: str,
    data: Any,
    *,
    indent: int | None = None,
    sort_keys: bool = False,
    content_type: str = "application/json",
) -> None:
    """Write JSON to S3."""
    text = json.dumps(data, indent=indent, sort_keys=sort_keys, allow_nan=False)
    write_text(s3, bucket, key, text, content_type=content_type)


def write_geojson(
    s3: S3Client,
    bucket: str,
    key: str,
    geojson: Any,
    *,
    indent: int | None = None,
) -> None:
    """Write GeoJSON to S3."""
    write_json(s3, bucket, key, geojson, indent=indent, content_type="application/geo+json")


def read_csv_df(
    s3: S3Client,
    bucket: str,
    key: str,
    **read_csv_kwargs: Any,
) -> pd.DataFrame:
    """Read a CSV from S3 into a DataFrame."""
    df: pd.DataFrame = pd.read_csv(io.BytesIO(read_bytes(s3, bucket, key)), **read_csv_kwargs)
    return df


def write_csv_df(
    s3: S3Client,
    bucket: str,
    key: str,
    df: pd.DataFrame,
    **write_csv_kwargs: Any,
) -> None:
    """Write a DataFrame to S3 as CSV."""
    buf = io.StringIO()
    df.to_csv(buf, **{"index": False, **write_csv_kwargs})
    write_text(s3, bucket, key, buf.getvalue(), content_type="text/csv")


def read_geojson_gdf(s3: S3Client, bucket: str, key: str) -> gpd.GeoDataFrame:
    """Read GeoJSON from S3 into a GeoDataFrame."""
    return gpd.read_file(io.BytesIO(read_bytes(s3, bucket, key)))


def write_geojson_gdf(s3: S3Client, bucket: str, key: str, gdf: gpd.GeoDataFrame) -> None:
    """Write a GeoDataFrame to S3 as GeoJSON."""
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    write_geojson(s3, bucket, key, json.loads(gdf.to_json(drop_id=True)))
