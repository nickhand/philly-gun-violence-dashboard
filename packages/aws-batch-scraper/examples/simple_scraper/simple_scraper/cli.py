"""Example CLI built with aws-batch-scraper."""

import typer
from aws_batch_scraper.cli import create_cli

from simple_scraper.config import SimpleSubmitterConfig, SimpleWorkerConfig
from simple_scraper.inputs import load_items
from simple_scraper.scraper import SimpleScraper

app = typer.Typer(help="Simple scraper example.")
app.add_typer(
    create_cli(
        name="scraper",
        script_name="simple-scraper",
        scraper_factory=SimpleScraper,
        input_loader=load_items,
        worker_config_class=SimpleWorkerConfig,
        submitter_config_class=SimpleSubmitterConfig,
    ),
    name="scraper",
)
