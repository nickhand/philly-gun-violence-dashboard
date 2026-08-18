"""Smoke tests for aws-batch-scraper examples."""

import sys
from pathlib import Path

from aws_batch_scraper.types import ScrapeStatus, WorkItem


def test_simple_scraper_example_imports_and_scrapes() -> None:
    """The documented simple scraper example should import and satisfy the contract."""
    repo_root = Path(__file__).resolve().parents[2]
    example_path = repo_root / "aws-batch-scraper" / "examples" / "simple_scraper"
    sys.path.insert(0, str(example_path))
    try:
        from simple_scraper.inputs import load_items
        from simple_scraper.scraper import SimpleScraper

        items = load_items(config=None)  # ty: ignore[invalid-argument-type]
        result = SimpleScraper()(WorkItem(item_id="alpha"))
    finally:
        sys.path.remove(str(example_path))

    assert [item.item_id for item in items] == ["alpha", "beta", "missing-gamma"]
    assert result.status == ScrapeStatus.SUCCESS
    assert result.data == {"item_id": "alpha", "extra": {}}
