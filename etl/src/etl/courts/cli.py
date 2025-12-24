from typing import Annotated, Literal

import typer
from loguru import logger

from etl.courts.batch.scrape import scrape as batch_scrape
from etl.courts.extract import PortalBatchConfig
from etl.courts.pipeline import update_courts

app = typer.Typer(name="courts", help="Courts portal ETL.")


@app.command()
def update(
    dry_run: Annotated[
        bool,
        typer.Option(help="Do everything except write outputs."),
    ] = False,
    sample: Annotated[
        int | None,
        typer.Option(help="Sample this many incident numbers."),
    ] = None,
    log_freq: Annotated[
        int,
        typer.Option(help="Log every N portal requests."),
    ] = 10,
    seed: Annotated[
        int,
        typer.Option(help="Random seed for sampling."),
    ] = 42,
    sleep: Annotated[
        int,
        typer.Option(help="Delay between portal requests."),
    ] = 2,
    ntasks: Annotated[
        int,
        typer.Option(help="Parallel ECS tasks to launch."),
    ] = 10,
    debug: Annotated[
        bool,
        typer.Option(help="Verbose logging."),
    ] = False,
) -> None:
    """Run the courts portal scraper in batch and update local flags."""
    cfg = PortalBatchConfig(
        dry_run=dry_run,
        sample=sample,
        log_freq=log_freq,
        seed=seed,
        sleep=sleep,
        ntasks=ntasks,
        debug=debug,
    )
    update_courts(cfg=cfg)
    logger.info("Courts flags updated using shootings processed geojson.")


@app.command()
def batch(
    input_csv: Annotated[
        str,
        typer.Argument(
            help="CSV path with incident/docket numbers (s3:// or local).",
        ),
    ],
    output_folder: Annotated[
        str,
        typer.Argument(
            help="Output folder for results (s3:// or local).",
        ),
    ],
    search_by: Annotated[
        Literal["Incident Number", "Docket Number"],
        typer.Option(help="Portal search field."),
    ] = "Incident Number",
    nprocs: Annotated[
        int,
        typer.Option(help="Total parallel splits."),
    ] = 1,
    pid: Annotated[
        int,
        typer.Option(help="This worker id (0-indexed)."),
    ] = 0,
    dry_run: Annotated[
        bool,
        typer.Option(help="Do everything except write outputs."),
    ] = False,
    sample: Annotated[
        int | None,
        typer.Option(help="Sample this many records before scraping."),
    ] = None,
    log_freq: Annotated[
        int,
        typer.Option(help="Log every N portal requests."),
    ] = 10,
    seed: Annotated[
        int,
        typer.Option(help="Random seed for sampling."),
    ] = 42,
    errors: Annotated[
        Literal["ignore", "raise"],
        typer.Option(help="Error handling mode."),
    ] = "ignore",
    sleep: Annotated[
        int,
        typer.Option(help="Delay between portal requests."),
    ] = 7,
    debug: Annotated[
        bool,
        typer.Option(help="Verbose logging."),
    ] = False,
) -> None:
    """Run the portal scraper batch job (manual inputs/outputs)."""
    batch_scrape(
        input_filename=input_csv,
        output_folder=output_folder,
        search_by=search_by,
        nprocs=nprocs,
        pid=pid,
        dry_run=dry_run,
        sample=sample,
        log_freq=log_freq,
        seed=seed,
        errors=errors,
        sleep=sleep,
        debug=debug,
    )
    logger.info("Courts batch scrape completed.")
