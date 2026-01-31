from typing import Annotated, Literal

import typer

from etl.courts.batch.scrape import scrape

app = typer.Typer(name="courts-batch", help="Batch courts portal scraper.")


@app.command()
def portal(
    input_csv: Annotated[
        str,
        typer.Argument(help="CSV path with incident/docket numbers (s3:// or local)."),
    ],
    output_folder: Annotated[
        str,
        typer.Argument(help="Output folder for results (s3:// or local)."),
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
        Literal["raise", "ignore"],
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
    """Run the portal scraper batch job."""
    scrape(
        input_filename=input_csv,
        output_folder=output_folder,
        search_by=search_by,
        nprocs=nprocs,
        shard_id=pid,
        dry_run=dry_run,
        sample=sample,
        log_freq=log_freq,
        seed=seed,
        errors=errors,
        sleep=sleep,
        debug=debug,
    )


if __name__ == "__main__":
    app()
