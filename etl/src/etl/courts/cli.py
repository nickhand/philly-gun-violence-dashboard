from typing import Annotated, Literal

import typer
from loguru import logger

from dashboard_utils.aws import make_s3_client
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
    errors: Annotated[
        Literal["ignore", "raise"],
        typer.Option(help="Error handling mode."),
    ] = "ignore",
    verify: Annotated[
        bool,
        typer.Option(
            "--verify/--no-verify",
            help="Enable verification mode with audit logging.",
        ),
    ] = False,
    no_retry: Annotated[
        bool,
        typer.Option(
            "--no-retry",
            help="Disable retry mechanism (max_attempts=1) for debugging.",
        ),
    ] = False,
) -> None:
    """Run the courts portal scraper in batch and update local flags.

    With --verify, enables classification of each scrape result and writes
    audit logs alongside the normal outputs.
    """
    # Create S3 client
    s3 = make_s3_client()

    # Build config
    cfg = PortalBatchConfig(
        dry_run=dry_run,
        sample=sample,
        log_freq=log_freq,
        seed=seed,
        sleep=sleep,
        ntasks=ntasks,
        debug=debug,
        errors=errors,
        verify=verify,
        no_retry=no_retry,
    )

    # Run update
    update_courts(s3, cfg=cfg)
    logger.info(
        f"Courts flags updated using shootings processed geojson"
        f"{' (with verification)' if verify else ''}."
    )


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
    shard_id: Annotated[
        int,
        typer.Option("--shard-id", help="This shard/worker id (0-indexed)."),
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
    verify: Annotated[
        bool,
        typer.Option(
            "--verify/--no-verify",
            help="Enable verification mode with audit logging and classification.",
        ),
    ] = False,
    run_id: Annotated[
        str | None,
        typer.Option(help="Run identifier for audit logging (verification mode)."),
    ] = None,
    no_retry: Annotated[
        bool,
        typer.Option(
            "--no-retry",
            help="Disable retry mechanism (max_attempts=1) for debugging.",
        ),
    ] = False,
) -> None:
    """Run the portal scraper batch job (manual inputs/outputs).

    With --verify, enables classification of each scrape result and writes
    audit logs (audit_attempts.ndjson.gz, audit_final.ndjson.gz) to output_folder.
    """
    batch_scrape(
        input_filename=input_csv,
        output_folder=output_folder,
        search_by=search_by,
        nprocs=nprocs,
        shard_id=shard_id,
        dry_run=dry_run,
        sample=sample,
        log_freq=log_freq,
        seed=seed,
        errors=errors,
        sleep=sleep,
        debug=debug,
        verify=verify,
        run_id=run_id,
        no_retry=no_retry,
    )
    logger.info(f"Courts batch scrape completed{' (with verification)' if verify else ''}.")


@app.command()
def diagnose(
    run_path: Annotated[
        str,
        typer.Argument(help="Path to run directory or merged audit directory."),
    ],
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show detailed incident lists."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON instead of formatted text."),
    ] = False,
    by_attempts: Annotated[
        int | None,
        typer.Option("--by-attempts", help="Output DC keys that took exactly N attempts."),
    ] = None,
    dc_key: Annotated[
        str | None,
        typer.Option("--dc-key", help="Look up audit record for a specific DC key."),
    ] = None,
    show_missing: Annotated[
        bool,
        typer.Option("--show-missing", help="Output DC keys that were never attempted."),
    ] = False,
) -> None:
    """Diagnose a scrape run and identify issues.

    Analyzes merged audit files and outputs:
    - Overall success/failure rates
    - Classification breakdown
    - Rate limiting detection
    - High retry incidents
    - Failure reasons
    - Shard health
    """
    from etl.courts.verification.diagnose import run as diagnose_run

    diagnose_run(
        run_path=run_path,
        verbose=verbose,
        json_output=json_output,
        by_attempts=by_attempts,
        dc_key=dc_key,
        show_missing=show_missing,
    )
