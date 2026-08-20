"""Stable generic result projection used for exact-run duplicate safety."""

from aws_batch_scraper.types import ScrapeResult

SEMANTIC_OBSERVATION_FIELDS = frozenset(
    {
        "status",
        "data",
        "classification",
        "subreason",
        "is_soft_blocked",
        "is_network_error",
        "final_url",
        "error_message",
    }
)


def semantic_observation(result: ScrapeResult) -> dict[str, object]:
    """Return the explicit generic projection used to compare observations."""
    return result.model_dump(mode="json", include=set(SEMANTIC_OBSERVATION_FIELDS))
