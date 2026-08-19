import typer
from loguru import logger

from dashboard_utils.aws import make_s3_client
from dashboard_utils.registry import get_geographic_data, iter_datasets, register_datasets

from .publication import (
    prepare_boundary_publication,
    read_boundary_manifest_etag,
    serialize_boundary_dataset,
    write_boundary_publication,
)

app = typer.Typer(
    name="boundaries",
    help="Boundary geographic datasets.",
    add_completion=False,
    no_args_is_help=True,
)


@app.command()
def extract() -> None:
    """Publish all registered boundaries as one atomic S3 generation."""
    s3 = make_s3_client()
    expected_manifest_etag = read_boundary_manifest_etag(s3)

    # Register the datasets
    register_datasets("etl.boundaries.extract")

    # Build and serialize every member before writing any object. Stable cache
    # keys remain untouched until the immutable generation pointer is complete.
    dataset_names = list(iter_datasets())
    serialized: dict[str, bytes] = {}
    for name in dataset_names:
        logger.info(f"Extracting geographic dataset: {name}")
        gdf = get_geographic_data(name, refresh=True, write_cache=False)
        serialized[name] = serialize_boundary_dataset(gdf)

    publication = prepare_boundary_publication(serialized)
    write_boundary_publication(
        s3,
        publication,
        expected_manifest_etag=expected_manifest_etag,
    )
    logger.info(f"Published boundary generation: sha256:{publication.release_id}")
