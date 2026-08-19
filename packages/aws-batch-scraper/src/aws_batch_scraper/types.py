"""Core types for the aws-batch-scraper framework."""

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RESERVED_WORK_MESSAGE_FIELDS = frozenset({"item_id", "run_id", "force_rescrape"})
_MAX_JSON_NESTING = 100


def _validate_json_value(
    value: object,
    *,
    path: str,
    depth: int = 0,
    active_containers: set[int] | None = None,
) -> None:
    """Reject values that cannot round-trip through the strict JSON protocol."""
    if depth > _MAX_JSON_NESTING:
        raise ValueError(f"{path} exceeds maximum JSON nesting of {_MAX_JSON_NESTING}")
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must not contain NaN or Infinity")
        return
    if not isinstance(value, (dict, list)):
        raise TypeError(f"{path} contains non-JSON value {type(value).__name__}")

    active = active_containers if active_containers is not None else set()
    identity = id(value)
    if identity in active:
        raise ValueError(f"{path} contains a cyclic JSON value")
    active.add(identity)
    try:
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise TypeError(f"{path} contains a non-string JSON object key")
                _validate_json_value(
                    child,
                    path=f"{path}.{key}",
                    depth=depth + 1,
                    active_containers=active,
                )
        else:
            for index, child in enumerate(value):
                _validate_json_value(
                    child,
                    path=f"{path}[{index}]",
                    depth=depth + 1,
                    active_containers=active,
                )
    finally:
        active.remove(identity)


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
        Values must use strict JSON types. Plugins can embed lookup context here
        (e.g. search type, date range).
    """

    item_id: str
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject ambiguous items before they reach the queue boundary."""
        self.validate()

    def validate(self) -> None:
        """Re-check invariants after any plugin mutation of ``extra``."""
        if not isinstance(self.item_id, str):
            raise TypeError("WorkItem.item_id must be a string")
        if not self.item_id.strip():
            raise ValueError("WorkItem.item_id must not be blank")
        if not isinstance(self.extra, dict):
            raise TypeError("WorkItem.extra must be a dictionary")
        if any(not isinstance(key, str) for key in self.extra):
            raise TypeError("WorkItem.extra keys must be strings")
        collisions = RESERVED_WORK_MESSAGE_FIELDS.intersection(self.extra)
        if collisions:
            fields = ", ".join(sorted(collisions))
            raise ValueError(f"WorkItem.extra contains reserved queue field(s): {fields}")
        _validate_json_value(self.extra, path="WorkItem.extra")


class WorkMessage(BaseModel):
    """Validated SQS envelope for one work item.

    Plugin-specific fields remain flat in the JSON body for backwards
    compatibility and are exposed through :attr:`extra_fields`.
    """

    model_config = ConfigDict(extra="allow", frozen=True, strict=True)

    item_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    force_rescrape: bool = False

    @field_validator("item_id", "run_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def _extra_is_strict_json(self) -> "WorkMessage":
        _validate_json_value(self.extra_fields, path="WorkMessage.extra")
        return self

    @property
    def extra_fields(self) -> dict[str, Any]:
        """Return plugin fields not owned by the queue protocol."""
        return dict(self.model_extra or {})

    def to_work_item(self) -> WorkItem:
        """Convert the validated envelope to the scraper-facing type."""
        return WorkItem(item_id=self.item_id, extra=self.extra_fields)

    @classmethod
    def from_work_item(
        cls,
        item: WorkItem,
        *,
        run_id: str,
        force_rescrape: bool = False,
    ) -> "WorkMessage":
        """Build an envelope without allowing plugin fields to shadow protocol fields."""
        item.validate()
        return cls.model_validate(
            {
                **item.extra,
                "item_id": item.item_id,
                "run_id": run_id,
                "force_rescrape": force_rescrape,
            }
        )


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
