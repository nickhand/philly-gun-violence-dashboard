"""Core types for the aws-batch-scraper framework."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, field_validator, model_validator


class ScrapeStatus(str, Enum):
    """High-level outcome of a single scrape attempt.

    Attributes
    ----------
    SUCCESS : str
        Item was found and data was extracted.
    NO_RESULTS : str
        Search completed but no matching records were found.
    FAILED : str
        Scrape failed after exhausting retries.
    INVALID_INPUT : str
        Input value was invalid and was never submitted.
    """

    SUCCESS = "SUCCESS"
    NO_RESULTS = "NO_RESULTS"
    FAILED = "FAILED"
    INVALID_INPUT = "INVALID_INPUT"


@dataclass
class WorkItem:
    """A single unit of work, drawn from an SQS message.

    Attributes
    ----------
    item_id : str
        Canonical identifier used as the S3 result key and for idempotency checks.
    extra : dict
        Any additional fields carried in the SQS message body beyond item_id/run_id.
        Plugins can embed lookup context here (e.g. search type, date range).
    """

    item_id: str
    extra: dict[str, Any] = field(default_factory=dict)


class ScrapeResult(BaseModel):
    """Outcome of a scrape attempt for a single item.

    Fields set by the scraper
    -------------------------
    status, data, classification, subreason, attempt_count, scrape_duration_s,
    is_soft_blocked, is_network_error, final_url, error_message, extra

    Fields set by the worker before writing to S3
    -----------------------------------------------
    item_id, scraped_at, run_id
    """

    # Set by the scraper
    status: ScrapeStatus
    data: dict[str, Any] | None = None
    classification: str = ""
    subreason: str | None = None
    attempt_count: int = 1
    scrape_duration_s: float | None = None
    # Retry-decision hints — worker uses these, not the classification string
    is_soft_blocked: bool = False
    is_network_error: bool = False
    # Observability metadata
    final_url: str | None = None
    error_message: str | None = None
    extra: dict[str, Any] | None = None

    # Set by the worker
    item_id: str | None = None
    scraped_at: datetime | None = None
    run_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_payload(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        if "item_id" not in normalized and "incident_number" in normalized:
            normalized["item_id"] = normalized["incident_number"]
        if "data" not in normalized and "results" in normalized:
            normalized["data"] = {"results": normalized["results"]}
        if "extra" not in normalized and "marker_hits" in normalized:
            normalized["extra"] = {"marker_hits": normalized["marker_hits"]}
        return normalized

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: object) -> object:
        if isinstance(value, str):
            return value.upper()
        return value


@dataclass
class FailureArtifact:
    """Additional artifact to write for a permanent scrape failure."""

    suffix: str
    body: bytes
    content_type: str


@dataclass
class WorkerStats:
    """Counters written to S3 at worker shutdown."""

    items_processed: int = 0
    success_count: int = 0
    no_results_count: int = 0
    soft_blocked_count: int = 0
    permanent_failure_count: int = 0

    def as_dict(self, *, task_id: str, run_id: str, runtime_seconds: float) -> dict[str, object]:
        items_per_minute = (
            (self.items_processed / runtime_seconds * 60) if runtime_seconds > 0 else 0
        )
        return {
            "task_id": task_id,
            "run_id": run_id,
            "items_processed": self.items_processed,
            "success_count": self.success_count,
            "no_results_count": self.no_results_count,
            "soft_blocked_count": self.soft_blocked_count,
            "permanent_failure_count": self.permanent_failure_count,
            "total_runtime_seconds": round(runtime_seconds, 1),
            "items_per_minute": round(items_per_minute, 1),
        }


@runtime_checkable
class Scraper(Protocol):
    """Protocol that all scraper plugins must satisfy.

    ``classify()`` is intentionally absent — how a plugin determines retry intent
    is its private concern. The worker reads ``is_soft_blocked`` and
    ``is_network_error`` from the returned ``ScrapeResult`` instead.
    """

    def __call__(self, item: WorkItem) -> ScrapeResult:
        """Scrape a single item and return the outcome."""
        ...

    def reset(self) -> None:
        """Reset internal state (browser, session, etc.) before a retry."""
        ...

    def close(self) -> None:
        """Release all resources held by this scraper instance."""
        ...
