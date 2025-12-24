from typing import Annotated

import typer
from loguru import logger

from etl.homicides.pipeline import update_homicide_totals

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
    update_homicide_totals(debug=debug, force=force, dry_run=dry_run)
    if dry_run:
        logger.info("Dry run complete; no files written.")
    else:
        logger.info("Homicide totals refreshed.")
