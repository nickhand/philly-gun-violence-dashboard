import json
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
from etl.courts.batch.aws import AWS
from etl.utils.aws import open_csv_from_s3


def get_output_paths(output_folder: str, chunk: int | None) -> tuple[str, str]:
    """Get the output paths for a chunk.

    Parameters
    ----------
    output_folder : str
        Base output folder (s3:// or local).
    chunk : int | None
        Chunk index, or None for no chunking.

    Returns
    -------
    tuple[str, str]
        Output folder and output filename.
    """
    if chunk is None:
        outfile = "portal_results.json"
    else:
        output_folder = f"{output_folder}/chunks"
        outfile = f"portal_results_{chunk}.json"

    outfile = f"{output_folder}/{outfile}"
    return output_folder, outfile


def _s3_exists(aws: AWS, path: str) -> bool:
    """Check if a path exists (s3:// or local)."""
    return aws.exists_on_s3(path) if path.startswith("s3://") else Path(path).exists()


def load_input_data(input_filename: str, aws: AWS) -> pd.Series:
    """Load the input data for the portal scraper (CSV of values).

    Parameters
    ----------
    input_filename : str
        Input CSV filename (s3:// or local).
    aws : AWS
        AWS helper instance.

    Returns
    -------
    pandas.Series
        Series of input values to scrape.
    """
    if not _s3_exists(aws, input_filename):
        raise ValueError(f"Input filename '{input_filename}' does not exist.")

    if not input_filename.endswith(".csv"):
        raise ValueError("Input file should end in .csv")

    # Load from s3
    if input_filename.startswith("s3://"):
        bucket, key = aws.split_s3_path(input_filename)
        with open_csv_from_s3(aws.s3, bucket=bucket, key=key) as f:
            out = pd.read_csv(
                f,
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
    outfile: str,
    results: list[str] | dict[str, list[dict[str, Any]] | None] | dict[str, Any] | pd.Series,
    aws: AWS,
) -> None:
    """Save the output data for the scraper.

    Parameters
    ----------
    outfile : str
        Output filename (s3:// or local).
    results : dict[str, list[dict[str, Any]] | None] | dict[str, Any] | pd.Series
        Results to save (list of dicts for JSON, DataFrame for CSV).
    aws : AWS
        AWS helper instance.
    """
    # Save to S3
    if outfile.startswith("s3://"):
        bucket, key = aws.split_s3_path(outfile)

        ## JSON
        if outfile.endswith(".json"):
            payload = json.dumps(results)
            aws.s3.put_object(Bucket=bucket, Key=key, Body=payload.encode())
        ## CSV
        elif outfile.endswith(".csv"):
            # The results need to be a pandas Series in this case
            assert isinstance(results, pd.Series)

            # Write CSV
            buf = StringIO()
            results.to_csv(buf, index=False, header=False)
            aws.s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue().encode())
        else:
            raise ValueError("Output file should end in .json or .csv")
    else:
        # Local
        p = Path(outfile)
        p.parent.mkdir(parents=True, exist_ok=True)

        ## JSON
        if outfile.endswith(".json"):
            p.write_text(json.dumps(results))

        ## CSV
        elif outfile.endswith(".csv"):
            # The results need to be a pandas Series in this case
            assert isinstance(results, pd.Series)
            results.to_csv(p, index=False, header=False)
        else:
            raise ValueError("Output file should end in .json or .csv")
