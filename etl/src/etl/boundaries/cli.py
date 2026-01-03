import typer
from loguru import logger

from dashboard_utils.aws import make_s3_client, write_json
from dashboard_utils.env import s3_settings
from dashboard_utils.registry import get_geographic_data, iter_datasets, register_datasets

app = typer.Typer(
    name="boundaries",
    help="Boundary geographic datasets.",
    add_completion=False,
    no_args_is_help=True,
)


def _write_manifest(datasets: list[str]) -> None:
    manifest = {
        "datasets": {dataset: f"reference/{dataset}.geojson" for dataset in datasets},
    }

    s3 = make_s3_client()
    write_json(
        s3,
        s3_settings.AWS_BUCKET_NAME,
        "reference/boundaries_manifest.json",
        manifest,
        indent=2,
    )


@app.command()
def extract() -> None:
    """Extract all registered boundary datasets into the local reference dir."""
    # Register the datasets
    register_datasets("etl.boundaries.extract")

    # Load each registered dataset
    dataset_names = list(iter_datasets())
    for name in dataset_names:
        logger.info(f"Extracting geographic dataset: {name}")
        _ = get_geographic_data(name, refresh=True)

    _write_manifest(dataset_names)
