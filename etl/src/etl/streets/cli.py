import typer
from loguru import logger

from dashboard_utils.aws import make_s3_client, write_geojson_gdf
from dashboard_utils.env import settings
from dashboard_utils.paths import get_processed_key
from dashboard_utils.registry import get_geographic_data, iter_datasets, register_datasets
from etl.streets.transform import centerlines_to_blocks

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

    key = get_processed_key("street_blocks")
    write_geojson_gdf(s3, settings.AWS_BUCKET_NAME, key, blocks)
    logger.info(f"Wrote street blocks to s3://{settings.AWS_BUCKET_NAME}/{key}")
