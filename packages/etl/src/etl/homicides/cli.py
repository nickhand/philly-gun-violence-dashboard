from typing import Annotated

import typer
from loguru import logger

from dashboard_utils.aws import make_s3_client
from etl.homicides.extract import extract_homicide_stats
from etl.homicides.pipeline import update_homicide_totals
from etl.utils.validation import require_columns, require_non_empty

app = typer.Typer(name="homicides", help="Homicide statistics ETL.")


@app.command()
def update(
    force: Annotated[
        bool,
        typer.Option(help="Skip monotonicity check on YTD totals."),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(help="Run Playwright in headed mode."),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option(help="Do everything except write updated homicide files.")
    ] = False,
) -> None:
    """Update homicide totals by scraping PPD crime stats and refreshing local data."""
    # Create S3 client
    s3 = make_s3_client()

    # Run update
    update_homicide_totals(s3, debug=debug, force=force, dry_run=dry_run)

    # Log completion
    if dry_run:
        logger.info("Dry run complete; no files written.")
    else:
        logger.info("Homicide totals refreshed.")


@app.command()
def smoke(
    debug: Annotated[
        bool,
        typer.Option(help="Run Playwright in headed mode."),
    ] = False,
) -> None:
    """Validate the live PPD homicide stats page without writing outputs."""
    as_of_date, annual_totals, ytd_totals = extract_homicide_stats(debug=debug)
    require_non_empty(annual_totals, "annual homicide totals")
    require_columns(annual_totals, ["year", "annual"], "annual homicide totals")
    require_non_empty(ytd_totals, "YTD homicide totals")
    require_columns(ytd_totals, ["year", "ytd"], "YTD homicide totals")
    logger.info(
        "Homicide source smoke check passed through {} with {} annual rows and {} YTD rows.",
        as_of_date.date(),
        len(annual_totals),
        len(ytd_totals),
    )
