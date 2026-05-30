import typer
from loguru import logger

from dashboard_utils.aws import make_s3_client
from dashboard_utils.processed import write_processed_geojson
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

    write_processed_geojson("street_blocks", blocks, s3=s3)
    logger.info("Wrote street blocks to S3")
