from typing import Annotated

import typer
from loguru import logger

from dashboard_utils.aws import make_s3_client
from etl.shootings.extract import fetch_shootings
from etl.shootings.pipeline import RAW_SHOOTINGS_COLUMNS, update_shootings
from etl.utils.validation import require_columns, require_non_empty

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


@app.command()
def smoke() -> None:
    """Validate the live CARTO shootings feed without writing outputs."""
    raw = fetch_shootings()
    require_non_empty(raw, "raw shootings extract")
    require_columns(raw, RAW_SHOOTINGS_COLUMNS, "raw shootings extract")
    logger.info("Shootings source smoke check passed with {:,d} rows.", len(raw))
