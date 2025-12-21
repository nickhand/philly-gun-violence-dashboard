import typer
from loguru import logger

from etl.courts.extract import PortalBatchConfig
from etl.courts.pipeline import merge_flags, update_courts

app = typer.Typer(name="courts", help="Courts portal ETL.")


@app.command()
def update(
    input_csv: str = typer.Option(
        None, help="Optional CSV with dc_key column; if omitted, use shootings loader."
    ),
    dry_run: bool = typer.Option(False, help="Do everything except write outputs."),
    sample: int | None = typer.Option(None, help="Sample this many incident numbers."),
    log_freq: int = typer.Option(10, help="Log every N portal requests."),
    seed: int = typer.Option(42, help="Random seed for sampling."),
    sleep: int = typer.Option(2, help="Delay between portal requests."),
    ntasks: int = typer.Option(10, help="Parallel ECS tasks to launch."),
    debug: bool = typer.Option(False, help="Verbose logging."),
):
    """
    Run the courts portal scraper in batch and update local flags.
    """

    cfg = PortalBatchConfig(
        dry_run=dry_run,
        sample=sample,
        log_freq=log_freq,
        seed=seed,
        sleep=sleep,
        ntasks=ntasks,
        debug=debug,
    )
    data = None
    if input_csv:
        import pandas as pd

        data = pd.read_csv(input_csv, dtype={"dc_key": str})
    update_courts(data=data, cfg=cfg)
    logger.info("Courts flags updated.")


@app.command()
def merge(input_csv: str, debug: bool = typer.Option(False)):
    """
    Merge courts flags into a CSV with a dc_key column and write to stdout.
    """
    import sys

    import pandas as pd

    df = pd.read_csv(input_csv, dtype={"dc_key": str})
    merged = merge_flags(df, debug=debug)
    merged.to_csv(sys.stdout, index=False)
    logger.info("Merged courts flags into %s", input_csv)
