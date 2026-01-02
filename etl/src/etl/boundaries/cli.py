import typer
from loguru import logger

from etl.utils.registry import get_geographic_data, iter_datasets, register_datasets

app = typer.Typer(
    name="boundaries",
    help="Boundary geographic datasets.",
    add_completion=False,
    no_args_is_help=True,
)


@app.command()
def extract() -> None:
    """Extract all registered boundary datasets into the local reference dir."""
    # Register the datasets
    register_datasets("etl.boundaries.extract")

    # Load each registered dataset
    for name in iter_datasets():
        logger.info(f"Extracting geographic dataset: {name}")
        _ = get_geographic_data(name, refresh=True)
