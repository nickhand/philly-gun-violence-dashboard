from pathlib import Path

import pandas as pd
import simplejson as json


def get_output_paths(output_folder, chunk):
    """Get the output paths."""

    if chunk is None:
        outfile = "portal_results.json"
    else:
        output_folder += "/chunks"
        outfile = f"portal_results_{chunk}.json"

    outfile = f"{output_folder}/{outfile}"
    return output_folder, outfile


def load_input_data(input_filename, aws):
    """
    Load the input data for the portal scraper (CSV of values).
    """
    if not aws.exists(input_filename):
        raise ValueError(f"Input filename '{input_filename}' does not exist.")

    opener = aws.remote.open if input_filename.startswith("s3://") else aws.local.open

    with opener(input_filename, "rb") as ff:
        if not input_filename.endswith(".csv"):
            raise ValueError("Input file should end in .csv")
        return pd.read_csv(ff, header=None, names=["value"], squeeze=True, dtype={"value": str})


def save_output_data(outfile, results, aws):
    """Save the output data for the scraper."""

    # Ensure local output dir exists
    if not outfile.startswith("s3://"):
        p = Path(outfile)
        if not p.parent.exists():
            p.parent.mkdir(parents=True)

    opener = aws.remote.open if outfile.startswith("s3://") else aws.local.open

    with opener(outfile, "w") as ff:
        if outfile.endswith(".json"):
            ff.write(json.dumps(results, ignore_nan=True))
        elif outfile.endswith(".csv"):
            results.to_csv(ff, index=False, header=False)
        else:
            raise ValueError("Output file should end in .json or .csv")
