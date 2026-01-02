from typing import Annotated

import typer
from loguru import logger

from dashboard_utils.aws import make_s3_client
from etl.shootings.pipeline import update_shootings

app = typer.Typer(name="shootings", help="Shooting victims ETL.")


@app.command()
def update(
    ignore_checks: Annotated[
        bool,
        typer.Option(help="Skip validation checks against existing shootings data."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(help="Run extraction and cleaning without writing outputs."),
    ] = False,
) -> None:
    """Refresh the shootings dataset from CARTO."""
    # Create S3 client
    s3 = make_s3_client()

    # Run the update process and log results
    update_shootings(s3, ignore_checks=ignore_checks, dry_run=dry_run)
    if dry_run:
        logger.info("Dry run complete; no files written.")
    else:
        logger.info("Shootings dataset refreshed.")
