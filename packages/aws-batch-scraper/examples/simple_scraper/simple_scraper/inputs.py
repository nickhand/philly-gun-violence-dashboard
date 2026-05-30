"""Example input loader."""

from aws_batch_scraper.config import SubmitterConfig
from aws_batch_scraper.types import WorkItem


def load_items(config: SubmitterConfig) -> list[WorkItem]:
    """Return a small fixed input set for local examples."""
    return [
        WorkItem(item_id="alpha", extra={"source": "example"}),
        WorkItem(item_id="beta", extra={"source": "example"}),
        WorkItem(item_id="missing-gamma", extra={"source": "example"}),
    ]
