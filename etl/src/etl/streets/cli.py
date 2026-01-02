import typer
from loguru import logger

from dashboard_utils.aws import make_s3_client, upload_file
from dashboard_utils.env import settings
from dashboard_utils.paths import data_dir, processed_data_dir
from etl.streets.transform import centerlines_to_blocks
from etl.utils.registry import get_geographic_data, iter_datasets, register_datasets

app = typer.Typer(name="streets", help="Street geographic datasets.")


@app.command()
def extract() -> None:
    """Extract all registered street datasets into the local reference dir."""
    # Register the datasets
    register_datasets("etl.streets.extract")

    # Load each registered dataset
    for name in iter_datasets():
        logger.info(f"Extracting geographic dataset: {name}")
        _ = get_geographic_data(name, refresh=True)


@app.command()
def load() -> None:
    """Load the cleaned and deduplicated street block dataset."""
    # Create S3 client
    s3 = make_s3_client()

    # Register the datasets
    register_datasets("etl.streets.extract")

    # Load the centerlines
    centerlines = get_geographic_data("street_centerlines")

    # Clean and de-duplicate
    blocks = centerlines_to_blocks(centerlines)
    logger.info(f"Deduplicated street blocks: {len(centerlines):,d} -> {len(blocks):,d}")

    # Ensure out dir exists
    out_dir = processed_data_dir() / "streets"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write to file
    out_path = out_dir.joinpath("street_blocks.geojson")
    blocks.to_file(out_path, driver="GeoJSON")
    logger.info(f"Wrote street blocks to: {out_path}")

    # Key in s3 is relative to data_dir
    key = str(out_path.relative_to(data_dir()))

    # Mirror to s3
    upload_file(
        s3,
        out_path,
        bucket=settings.AWS_BUCKET_NAME,
        key=key,
        content_type="application/geo+json",
    )
