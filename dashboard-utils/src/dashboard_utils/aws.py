import io
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import boto3
import geopandas as gpd
import pandas as pd
from botocore.exceptions import ClientError
from mypy_boto3_s3.client import S3Client
from mypy_boto3_s3.literals import BucketLocationConstraintType

from dashboard_utils.config import get_aws_settings


# ----------------------------
# Client/session
# ----------------------------
@lru_cache(maxsize=1)
def make_boto3_session(*, region_name: str | None = None) -> boto3.Session:
    """
    Create a boto3 Session with sensible defaults.

    Parameters
    ----------
    region_name
        Optional override. If None, uses the configured aws_region.

    Returns
    -------
    boto3.Session
        The boto3 Session.
    """
    settings = get_aws_settings()
    resolved_region = region_name or str(settings.aws_region)
    print("Resolved AWS region:", resolved_region)
    print("AWS settings:", settings)

    session = boto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        profile_name=settings.aws_profile,
        region_name=resolved_region,
    )

    if not session.region_name:
        raise RuntimeError(
            "AWS region is not configured. Set AWS_REGION/AWS_DEFAULT_REGION "
            "or configure `region = ...` in your AWS profile (~/.aws/config)."
        )

    return session


@lru_cache(maxsize=1)
def make_s3_client(*, region_name: str | None = None) -> S3Client:
    """
    Create a boto3 S3 client with sensible retries.

    Parameters
    ----------
    region_name
        Optional override. If None, boto3 resolves the region from env/profile/runtime.

    Returns
    -------
    S3Client
        The S3 client.
    """
    session = make_boto3_session(region_name=region_name)
    return session.client("s3")


# ----------------------------
# Small utilities
# ----------------------------


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """Parse 's3://bucket/key' and return (bucket, key).

    Parameters
    ----------
    uri : str
        The S3 URI to parse; must begin with 's3://'.

    Returns
    -------
    tuple[str, str]
        The (bucket, key) tuple.
    """
    if not uri.startswith("s3://"):
        raise ValueError(f"Not an s3:// URI: {uri!r}")

    # Trim the 's3://' prefix
    rest = uri[5:]

    # Split into bucket and key
    bucket, sep, key = rest.partition("/")

    # Validate the components
    if not sep or not bucket or not key:
        raise ValueError(f"Invalid s3:// URI (expected s3://bucket/key): {uri}")

    return bucket, key


def _raise_if_not_found(err: ClientError, bucket: str, key: str) -> None:
    """Raise FileNotFoundError if the ClientError indicates a missing S3 object."""
    code = err.response.get("Error", {}).get("Code")
    if code in {"NoSuchKey", "404"}:
        raise FileNotFoundError(f"S3 object not found: s3://{bucket}/{key}") from err
    raise err


def exists_on_s3(s3: S3Client, path: str) -> bool:
    """Return True if the given S3 object exists.

    Parameters
    ----------
    path : str
        S3 path (s3://bucket/key).

    Returns
    -------
    bool
        True if the S3 object exists.
    """
    bucket, key = parse_s3_uri(path)
    response = s3.list_objects_v2(Bucket=bucket, Prefix=key, MaxKeys=1)
    keycount: int = response.get("KeyCount", 0)
    return keycount > 0


def ensure_bucket(s3: S3Client, bucket: str, *, region: str | None = None) -> None:
    """
    Ensure an S3 bucket exists. If it doesn't, create it.

    Notes
    -----
    - If you don't have permission to `s3:HeadBucket` or `s3:CreateBucket`, this will raise.
    - If the bucket name is already taken by another AWS account, create will raise.
    """
    try:
        s3.head_bucket(Bucket=bucket)
        return
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")

        # Not found => create
        if code in {"404", "NoSuchBucket", "NotFound"}:
            pass
        # Permission issues should be surfaced
        elif code in {"403", "AccessDenied"}:
            raise PermissionError(f"Access denied checking bucket: {bucket!r}") from e
        else:
            raise

    # Pick a region: explicit arg > client region > fail
    region = region or getattr(getattr(s3, "meta", None), "region_name", None)
    if not region:
        raise RuntimeError(
            "Cannot determine region for bucket creation. "
            "Pass region=... or configure AWS_REGION/AWS_DEFAULT_REGION."
        )

    try:
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket)
        else:
            lc = cast(BucketLocationConstraintType, region)
            s3.create_bucket(
                Bucket=bucket,
                CreateBucketConfiguration={"LocationConstraint": lc},
            )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in {"BucketAlreadyOwnedByYou"}:
            return
        raise


# ----------------------------
# Bytes / text
# ----------------------------


def read_bytes(s3: S3Client, bucket: str, key: str) -> bytes:
    """Read an S3 object fully into memory as bytes.

    Parameters
    ----------
    s3 : S3Client
        The S3 client.
    bucket : str
        The S3 bucket name.
    key : str
        The S3 object key.

    Returns
    -------
    bytes
        The object data.
    """
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except ClientError as e:
        _raise_if_not_found(e, bucket, key)
        raise


def write_bytes(
    s3: S3Client,
    bucket: str,
    key: str,
    data: bytes,
    *,
    content_type: str | None = None,
) -> None:
    """Write bytes to S3.

    Parameters
    ----------
    s3 : S3Client
        The S3 client.
    bucket : str
        The S3 bucket name.
    key : str
        The S3 object key.
    data : bytes
        The data to write.
    content_type : str | None, optional
        Optional content type to set on the object.
    """
    if content_type:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    else:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
        )


def read_text(s3: S3Client, bucket: str, key: str, *, encoding: str = "utf-8") -> str:
    """Read an S3 object fully into memory as text.

    Parameters
    ----------
    s3 : S3Client
        The S3 client.
    bucket : str
        The S3 bucket name.
    key : str
        The S3 object key.
    encoding : str, optional
        The text encoding (default is 'utf-8').

    Returns
    -------
    str
        The object data as text.
    """
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
    """Write text to S3.

    Parameters
    ----------
    s3 : S3Client
        The S3 client.
    bucket : str
        The S3 bucket name.
    key : str
        The S3 object key.
    text : str
        The text data to write.
    encoding : str, optional
        The text encoding (default is 'utf-8').
    content_type : str | None, optional
        Optional content type to set on the object.
    """
    write_bytes(
        s3,
        bucket,
        key,
        text.encode(encoding),
        content_type=content_type,
    )


# ----------------------------
# JSON / GeoJSON
# ----------------------------


def read_json(s3: S3Client, bucket: str, key: str) -> Any:
    """Read JSON (or GeoJSON) from S3 and return Python objects (dict/list).

    Parameters
    ----------
    s3 : S3Client
        The S3 client.
    bucket : str
        The S3 bucket name.
    key : str
        The S3 object key.

    Returns
    -------
    Any
        The parsed JSON data.
    """
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
    """Write JSON (or GeoJSON) to S3.

    Parameters
    ----------
    s3 : S3Client
        The S3 client.
    bucket : str
        The S3 bucket name.
    key : str
        The S3 object key.
    data : Any
        The data to serialize as JSON.
    indent : int | None, optional
        Optional indentation level for pretty-printing (default is None).
    sort_keys : bool, optional
        Whether to sort the keys in the output (default is False).
    content_type : str, optional
        The content type to set on the object (default is 'application/json').
    """
    text = json.dumps(
        data,
        indent=indent,
        sort_keys=sort_keys,
        allow_nan=False,
    )
    write_text(s3, bucket, key, text, content_type=content_type)


def write_geojson(
    s3: S3Client,
    bucket: str,
    key: str,
    geojson: Any,
    *,
    indent: int | None = None,
) -> None:
    """
    Write GeoJSON to S3 (sets a GeoJSON-ish content type).

    Parameters
    ----------
    s3 : S3Client
        The S3 client.
    bucket : str
        The S3 bucket name.
    key : str
        The S3 object key.
    geojson : Any
        The GeoJSON data to serialize.
    indent : int | None, optional
        Optional indentation level for pretty-printing (default is None).
    """
    write_json(
        s3,
        bucket,
        key,
        geojson,
        indent=indent,
        content_type="application/geo+json",
    )


# ----------------------------
# CSV (pandas)
# ----------------------------


def read_csv_df(
    s3: S3Client,
    bucket: str,
    key: str,
    **read_csv_kwargs: Any,
) -> pd.DataFrame:
    """
    Read a CSV from S3 into a pandas DataFrame.

    Parameters
    ----------
    s3 : S3Client
        The S3 client.
    bucket : str
        The S3 bucket name.
    key : str
        The S3 object key.
    **read_csv_kwargs : Any
        Additional keyword arguments to pass to pandas.read_csv().
    """
    raw = read_bytes(s3, bucket, key)
    df: pd.DataFrame = pd.read_csv(io.BytesIO(raw), **read_csv_kwargs)
    return df


def write_csv_df(
    s3: S3Client,
    bucket: str,
    key: str,
    df: pd.DataFrame,
    **write_csv_kwargs: Any,
) -> None:
    """
    Write a pandas DataFrame to S3 as CSV.

    Parameters
    ----------
    s3 : S3Client
        The S3 client.
    bucket : str
        The S3 bucket name.
    key : str
        The S3 object key.
    df : pd.DataFrame
        The DataFrame to write.
    **write_csv_kwargs : Any
        Additional keyword arguments to pass to DataFrame.to_csv().
    """
    # Ensure index is not written by default
    kwargs = {"index": False, **write_csv_kwargs}

    # Write to an in-memory buffer first
    buf = io.StringIO()
    df.to_csv(buf, **kwargs)

    # Write the buffer contents to S3
    write_text(s3, bucket, key, buf.getvalue(), content_type="text/csv")


# ----------------------------
# GeoJSON (geopandas)
# ----------------------------


def read_geojson_gdf(s3: S3Client, bucket: str, key: str) -> gpd.GeoDataFrame:
    """
    Read GeoJSON from S3 into a GeoPandas GeoDataFrame.

    Parameters
    ----------
    s3 : S3Client
        The S3 client.
    bucket : str
        The S3 bucket name.
    key : str
        The S3 object key.

    Returns
    -------
    gpd.GeoDataFrame
        The loaded GeoDataFrame.
    """
    raw = read_bytes(s3, bucket, key)
    return gpd.read_file(io.BytesIO(raw))


def write_geojson_gdf(s3: S3Client, bucket: str, key: str, gdf: gpd.GeoDataFrame) -> None:
    """
    Write a GeoPandas GeoDataFrame to S3 as GeoJSON.

    The GeoDataFrame is automatically converted to EPSG:4326 (WGS84) before writing,
    as this is the standard CRS for GeoJSON and web mapping libraries.

    Parameters
    ----------
    s3 : S3Client
        The S3 client.
    bucket : str
        The S3 bucket name.
    key : str
        The S3 object key.
    gdf : gpd.GeoDataFrame
        The GeoDataFrame to write.
    """
    # Convert to WGS84 (EPSG:4326) for GeoJSON standard compliance
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    write_geojson(s3, bucket, key, json.loads(gdf.to_json(drop_id=True)))


# ----------------------------
# File transfers
# ----------------------------


def download_file(s3: S3Client, bucket: str, key: str, filename: str | Path) -> None:
    """Download an S3 object to a local file.

    Parameters
    ----------
    s3 : S3Client
        The S3 client.
    bucket : str
        The S3 bucket name.
    key : str
        The S3 object key.
    filename : str | Path
        The local filename to download to.
    """
    try:
        s3.download_file(bucket, key, str(filename))
    except ClientError as e:
        _raise_if_not_found(e, bucket, key)
        raise


def upload_file(
    s3: S3Client,
    filename: str | Path,
    bucket: str,
    key: str,
    *,
    content_type: str | None = None,
) -> None:
    """Upload a local file to S3.

    Parameters
    ----------
    s3 : S3Client
        The S3 client.
    filename : str | Path
        The local filename to upload.
    bucket : str
        The S3 bucket name.
    key : str
        The S3 object key.
    content_type : str | None, optional
        The content type of the file (default is None).
    """
    extra = {"ContentType": content_type} if content_type else None
    s3.upload_file(str(filename), bucket, key, ExtraArgs=extra)
