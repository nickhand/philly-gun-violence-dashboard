from pathlib import Path
from typing import Any

import pandas as pd
from mypy_boto3_s3.client import S3Client

from dashboard_utils.aws import exists_on_s3, parse_s3_uri, read_csv_df, write_csv_df, write_json
from etl.courts.batch.aws import AWS

# Type alias for save_output_data results parameter
type OutputResults = (
    list[str]
    | list[dict[str, Any]]
    | dict[str, list[dict[str, Any]] | None]
    | dict[str, Any]
    | pd.Series[Any]
)


def get_output_paths(output_folder: str, shard_id: int | None) -> tuple[str, str]:
    """Get the output paths for a shard.

    Parameters
    ----------
    output_folder : str
        Base shards folder (s3:// or local), e.g., 's3://bucket/runs/{run_id}/shards'.
    shard_id : int | None
        Shard index (0-based), or None for single-worker mode.

    Returns
    -------
    tuple[str, str]
        Shard output folder and results filename.

    Notes
    -----
    Structure:
    - Single worker: {output_folder}/results.json
    - Multi-worker: {output_folder}/shard-{NN}/results.json
    """
    if shard_id is None:
        # Single-worker mode: write directly to output_folder
        shard_folder = output_folder
        outfile = f"{output_folder}/results.json"
    else:
        # Multi-worker mode: shard-{NN}/results.json
        shard_folder = f"{output_folder}/shard-{shard_id:02d}"
        outfile = f"{shard_folder}/results.json"

    return shard_folder, outfile


def _path_exists(s3: S3Client, path: str) -> bool:
    """Check if a path exists (s3:// or local)."""
    return exists_on_s3(s3, path) if path.startswith("s3://") else Path(path).exists()


def load_input_data(s3: S3Client, input_filename: str, aws: AWS) -> pd.Series:
    """Load the input data for the portal scraper (CSV of values).

    Parameters
    ----------
    s3: S3Client
        The S3 client to use.
    input_filename : str
        Input CSV filename (s3:// or local).
    aws : AWS
        AWS helper instance.

    Returns
    -------
    pandas.Series
        Series of input values to scrape.
    """
    if not _path_exists(s3, input_filename):
        raise ValueError(f"Input filename '{input_filename}' does not exist.")

    if not input_filename.endswith(".csv"):
        raise ValueError("Input file should end in .csv")

    # Load from s3
    if input_filename.startswith("s3://"):
        bucket, key = parse_s3_uri(input_filename)
        out = read_csv_df(
            s3,
            bucket=bucket,
            key=key,
            header=None,
            names=["value"],
            dtype={"value": str},
        )
    # Local
    else:
        with open(input_filename, "rb") as ff:
            out = pd.read_csv(
                ff,
                header=None,
                names=["value"],
                dtype={"value": str},
            )

    return out["value"]  # Return a Series


def save_output_data(
    aws: AWS,
    *,
    outfile: str,
    results: OutputResults,
) -> None:
    """Save the output data for the scraper to s3.

    Parameters
    ----------
    s3: S3Client
        The S3 client to use.
    outfile : str
        Output filename (s3:// or local).
    results : list | dict | pd.Series
        Results to save (list of dicts for JSON, DataFrame for CSV).
    aws : AWS
        AWS helper instance.
    """
    # Save to S3
    if outfile.startswith("s3://"):
        assert aws is not None, "AWS instance must be provided for S3 saving"
        bucket, key = parse_s3_uri(outfile)

        ## JSON
        if outfile.endswith(".json"):
            write_json(aws.s3, bucket=bucket, key=key, data=results)
        ## CSV
        elif outfile.endswith(".csv"):
            # The results need to be a pandas Series in this case
            assert isinstance(results, pd.Series)

            # Write as DataFrame for CSV
            write_csv_df(
                aws.s3,
                bucket=bucket,
                key=key,
                df=results.to_frame(name="value"),
                index=False,
                header=False,
            )
        else:
            raise ValueError("Output file should end in .json or .csv")
    else:
        raise ValueError("To save output files to s3, provide an S3 path starting with 's3://'")
