"""Aggregate per-item results from S3 into a combined dict."""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Literal

from loguru import logger
from mypy_boto3_s3.client import S3Client
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from aws_batch_scraper.config import WorkerConfig
from aws_batch_scraper.types import ScrapeResult, WorkItem

_FETCH_WORKERS = 30


class RunManifest(BaseModel):
    """Typed subset required to prove an exact run is safe to aggregate."""

    model_config = ConfigDict(extra="allow", frozen=True, strict=True)

    run_id: str = Field(min_length=1)
    selection_mode: Literal["sample", "incremental", "full"]
    candidate_count: int = Field(ge=1)
    input_size: int = Field(ge=1)
    completed_at: AwareDatetime | None = None

    @field_validator("run_id")
    @classmethod
    def _run_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run_id must not be blank")
        return value

    @field_validator("completed_at", mode="before")
    @classmethod
    def _parse_completed_at(cls, value: object) -> object:
        if value is None or isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            raise ValueError("completed_at must be an ISO timestamp")
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("completed_at must be an ISO timestamp") from exc

    @model_validator(mode="after")
    def _selection_counts_are_consistent(self) -> "RunManifest":
        if self.input_size > self.candidate_count:
            raise ValueError("input_size cannot exceed candidate_count")
        if self.selection_mode == "full" and self.input_size != self.candidate_count:
            raise ValueError("a full run must select every candidate input")
        return self


class RunResultConflictError(RuntimeError):
    """Raised when durable evidence says an exact run has conflicting results."""


def _reject_json_constant(value: str) -> None:
    """Reject JavaScript-only numeric tokens such as NaN and Infinity."""
    raise ValueError(f"non-standard JSON constant is not allowed: {value}")


def read_run_manifest(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
    *,
    require_completed: bool = False,
) -> RunManifest:
    """Read and validate the typed identity/count contract for one run."""
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/manifest.json"
    body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
    try:
        decoded: object = json.loads(body, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"Run manifest for {run_id} is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"Run manifest for {run_id} must be a JSON object")
    try:
        manifest = RunManifest.model_validate(decoded)
    except ValueError as exc:
        raise ValueError(f"Run manifest for {run_id} is invalid") from exc
    if manifest.run_id != run_id:
        raise ValueError(
            f"Run manifest identity {manifest.run_id!r} does not match requested run {run_id!r}"
        )
    if require_completed and manifest.completed_at is None:
        raise ValueError(f"Run {run_id} has not been completed by its task monitor")
    return manifest


def _aggregate_prefix(
    s3: S3Client,
    config: WorkerConfig,
    *,
    prefix: str,
    expected_run_id: str | None,
) -> dict[str, ScrapeResult]:
    """Fetch and validate every JSON result below one S3 prefix."""
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix)

    keys: list[tuple[str, str]] = []
    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".json"):
                continue
            item_id = key.removeprefix(prefix).removesuffix(".json")
            if item_id:
                keys.append((item_id, key))

    logger.info(f"Fetching {len(keys)} result files from s3://{config.s3_bucket}/{prefix}")

    def _fetch(item_key: tuple[str, str]) -> tuple[str, ScrapeResult]:
        item_id, key = item_key
        body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        result = ScrapeResult.model_validate_json(body)
        if expected_run_id is not None and result.run_id != expected_run_id:
            raise ValueError(
                f"Result {item_id} belongs to run {result.run_id!r}, expected {expected_run_id!r}"
            )
        if expected_run_id is not None and result.item_id != item_id:
            raise ValueError(f"Result key {item_id!r} contains item identity {result.item_id!r}")
        return item_id, result

    total = len(keys)
    results: dict[str, ScrapeResult] = {}
    log_every = max(1, total // 10)
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
        futures = {pool.submit(_fetch, ik): ik for ik in keys}
        for future in as_completed(futures):
            item_id, key = futures[future]
            try:
                fetched_item_id, result = future.result()
            except Exception:
                logger.exception(f"Failed to fetch or validate result for {item_id} ({key})")
                raise
            results[fetched_item_id] = result
            done = len(results)
            if done % log_every == 0:
                logger.info(f"Fetched {done}/{total} results ({done / total * 100:.0f}%)")

    logger.info(f"Aggregated {len(results)} results")
    return results


def aggregate_results(
    s3: S3Client,
    config: WorkerConfig,
    *,
    run_id: str | None = None,
) -> dict[str, ScrapeResult]:
    """Read global cached results or conclusive observations for one exact run."""
    if run_id is None:
        prefix = f"{config.s3_scraper_prefix}/results/"
    else:
        require_no_result_conflicts(s3, config, run_id)
        prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/results/"
    return _aggregate_prefix(
        s3,
        config,
        prefix=prefix,
        expected_run_id=run_id,
    )


def aggregate_failures(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> dict[str, ScrapeResult]:
    """Read permanent failure observations for one exact run."""
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/failures/"
    return _aggregate_prefix(
        s3,
        config,
        prefix=prefix,
        expected_run_id=run_id,
    )


def require_no_result_conflicts(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> None:
    """Fail closed before publishing a run that has any conflict evidence."""
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/result-conflicts/"
    paginator = s3.get_paginator("list_objects_v2")
    conflict_keys: list[str] = []
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if isinstance(key, str) and key.startswith(prefix) and key != prefix:
                conflict_keys.append(key)

    if conflict_keys:
        sample = ", ".join(sorted(conflict_keys)[:10])
        remainder = len(conflict_keys) - 10
        suffix = f" (and {remainder} more)" if remainder > 0 else ""
        raise RunResultConflictError(
            f"Run {run_id} has {len(conflict_keys)} durable result conflict(s): "
            f"{sample}{suffix}. Refusing to aggregate or publish this run."
        )


def read_run_items(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
    *,
    require_completed: bool = False,
) -> list[WorkItem]:
    """Read and validate the immutable input set submitted for one run.

    When ``require_completed`` is true, processing is permitted only after the
    task monitor has finalized the exact run manifest. This prevents a manual
    or duplicated workflow dispatch from publishing while workers are live.
    """
    manifest = read_run_manifest(s3, config, run_id, require_completed=require_completed)

    key = f"{config.s3_scraper_prefix}/runs/{run_id}/input.jsonl"
    body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
    try:
        text = body.decode()
    except UnicodeDecodeError as exc:
        raise ValueError(f"Run input for {run_id} is not UTF-8") from exc

    items: list[WorkItem] = []
    seen: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            decoded: object = json.loads(line, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(
                f"Run input for {run_id} has invalid JSON on line {line_number}"
            ) from exc
        if not isinstance(decoded, dict):
            raise ValueError(f"Run input for {run_id} line {line_number} must be an object")
        fields = dict(decoded)
        item_id = fields.pop("item_id", None)
        if not isinstance(item_id, str):
            raise ValueError(f"Run input for {run_id} line {line_number} needs a string item_id")
        item = WorkItem(item_id=item_id, extra=fields)
        if item.item_id in seen:
            raise ValueError(f"Run input for {run_id} contains duplicate item {item.item_id}")
        seen.add(item.item_id)
        items.append(item)

    if not items:
        raise ValueError(f"Run input for {run_id} contains no work items")
    if len(items) != manifest.input_size:
        raise ValueError(
            f"Run input for {run_id} contains {len(items)} work items, "
            f"but its manifest declares {manifest.input_size}"
        )
    return items
