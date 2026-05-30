"""Example scraper implementation."""

from aws_batch_scraper.types import ScrapeResult, ScrapeStatus, WorkItem


class SimpleScraper:
    """Toy scraper that echoes each item ID."""

    def __call__(self, item: WorkItem) -> ScrapeResult:
        if item.item_id.startswith("missing"):
            return ScrapeResult(status=ScrapeStatus.NO_RESULTS, classification="NO_MATCH")
        return ScrapeResult(
            status=ScrapeStatus.SUCCESS,
            data={"item_id": item.item_id, "extra": item.extra},
            classification="ECHO",
        )

    def reset(self) -> None:
        """Reset transient resources before retry."""

    def close(self) -> None:
        """Release resources at worker shutdown."""
