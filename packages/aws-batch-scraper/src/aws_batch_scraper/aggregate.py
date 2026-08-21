"""Aggregate per-item results from S3 into a combined dict."""

import base64
import binascii
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypeGuard

from botocore.exceptions import ClientError
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
from aws_batch_scraper.resolution_paths import RESULT_CONFLICT_RESOLUTION_ROOT
from aws_batch_scraper.result_semantics import (
    SEMANTIC_OBSERVATION_FIELDS,
    semantic_observation,
)
from aws_batch_scraper.strict_json import decode_strict_json_object
from aws_batch_scraper.terminal_journal import (
    CandidateJournalError,
    TerminalCandidateResolution,
    read_terminal_candidate_resolutions,
)
from aws_batch_scraper.types import ScrapeResult, ScrapeStatus, WorkItem

_FETCH_WORKERS = 30
RESULT_CONFLICT_POLICY_VERSION = 1
_RESOLUTION_SCHEMA_VERSION = 1


def _result_conflict_evidence_digest(entries: list[dict[str, object]]) -> str:
    """Bind a deterministic evidence inventory to its adjudication policy."""
    body = json.dumps(
        {
            "conflict_policy_version": RESULT_CONFLICT_POLICY_VERSION,
            "entries": entries,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(body).hexdigest()


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


@dataclass(frozen=True)
class ResultConflictReport:
    """Deterministic disposition of all immutable conflict evidence for one run."""

    conflict_policy_version: int
    total_count: int
    resolved_count: int
    unresolved_count: int
    evidence_sha256: str
    resolved_keys: tuple[str, ...] = ()
    unresolved_keys: tuple[str, ...] = ()
    invalid_resolution_count: int = 0
    invalid_resolution_keys: tuple[str, ...] = ()

    @classmethod
    def empty(cls) -> "ResultConflictReport":
        """Return the stable report for a run with no conflict objects."""
        return cls(
            conflict_policy_version=RESULT_CONFLICT_POLICY_VERSION,
            total_count=0,
            resolved_count=0,
            unresolved_count=0,
            evidence_sha256=_result_conflict_evidence_digest([]),
        )


def _reject_json_constant(value: str) -> None:
    """Reject JavaScript-only numeric tokens such as NaN and Infinity."""
    raise ValueError(f"non-standard JSON constant is not allowed: {value}")


def _is_sha256(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_conflict_identity(
    record: dict[str, object],
    *,
    run_id: str,
    prefix: str,
    key: str,
) -> tuple[str, str, str, str, str, tuple[str, ...]]:
    """Return item/existing/candidate/status for one well-bound conflict record."""
    schema_version = record.get("schema_version")
    if type(schema_version) is not int or schema_version not in {1, 2}:
        raise ValueError("unsupported conflict schema version")
    if record.get("terminal_status") != "result-conflict" or record.get("run_id") != run_id:
        raise ValueError("conflict terminal/run identity is invalid")
    item_id = record.get("item_id")
    if not isinstance(item_id, str) or not item_id:
        raise ValueError("conflict item identity is invalid")
    existing_sha256 = record.get("existing_sha256")
    candidate_sha256 = record.get("candidate_sha256")
    if not _is_sha256(existing_sha256) or not _is_sha256(candidate_sha256):
        raise ValueError("conflict body digest is invalid")
    existing_status = record.get("existing_status")
    if not isinstance(existing_status, str) or existing_status not in {
        ScrapeStatus.SUCCESS.value,
        ScrapeStatus.NO_RESULTS.value,
    }:
        raise ValueError("conflict canonical status is not conclusive")
    candidate_status = record.get("candidate_status")
    if not isinstance(candidate_status, str) or candidate_status not in {
        ScrapeStatus.SUCCESS.value,
        ScrapeStatus.NO_RESULTS.value,
    }:
        raise ValueError("conflict candidate status is not conclusive")
    differing_fields = record.get("differing_fields")
    if (
        not isinstance(differing_fields, list)
        or not differing_fields
        or any(not isinstance(field, str) or not field for field in differing_fields)
        or differing_fields != sorted(set(differing_fields))
    ):
        raise ValueError("conflict differing_fields is invalid")

    relative_key = key.removeprefix(prefix)
    expected_relative_key = (
        f"{item_id}.json" if schema_version == 1 else f"v2/{item_id}/{candidate_sha256}.json"
    )
    if relative_key != expected_relative_key:
        raise ValueError("conflict key does not match its schema/item/candidate identity")
    return (
        item_id,
        existing_sha256,
        candidate_sha256,
        existing_status,
        candidate_status,
        tuple(differing_fields),
    )


def _read_canonical_result(
    s3: S3Client,
    config: WorkerConfig,
    *,
    run_id: str,
    item_id: str,
    expected_sha256: str,
    expected_status: str,
) -> tuple[str, bytes, ScrapeResult]:
    canonical_key = f"{config.s3_scraper_prefix}/runs/{run_id}/results/{item_id}.json"
    canonical_body = s3.get_object(
        Bucket=config.s3_bucket,
        Key=canonical_key,
    )["Body"].read()
    if hashlib.sha256(canonical_body).hexdigest() != expected_sha256:
        raise ValueError("canonical result does not match the conflict body digest")
    canonical_object = decode_strict_json_object(
        canonical_body,
        label=f"Canonical result {canonical_key}",
    )
    canonical = ScrapeResult.model_validate(canonical_object)
    if canonical.item_id != item_id or canonical.run_id != run_id:
        raise ValueError("canonical result identity does not match the conflict")
    if canonical.status.value != expected_status or canonical.status not in {
        ScrapeStatus.SUCCESS,
        ScrapeStatus.NO_RESULTS,
    }:
        raise ValueError("canonical result status does not match the conflict")
    if canonical.is_soft_blocked or canonical.is_network_error:
        raise ValueError("canonical conclusive result still carries a retry hint")
    return canonical_key, canonical_body, canonical


def _validate_v2_conflict_evidence(
    record: dict[str, object],
    *,
    run_id: str,
    item_id: str,
    candidate_sha256: str,
    canonical_key: str,
    canonical: ScrapeResult,
) -> None:
    """Cryptographically validate retained schema-v2 candidate evidence."""
    if record.get("canonical_result_key") != canonical_key:
        raise ValueError("v2 conflict canonical key is invalid")
    candidate_evidence = record.get("candidate_evidence")
    existing_evidence = record.get("existing_evidence")
    if not isinstance(candidate_evidence, dict) or not isinstance(existing_evidence, dict):
        raise ValueError("v2 conflict retained evidence is missing")
    if set(candidate_evidence) != {
        "body_sha256",
        "body_base64",
        "semantic_observation",
        "result",
    }:
        raise ValueError("v2 candidate evidence fields are invalid")
    if set(existing_evidence) != {"body_sha256", "semantic_observation", "result"}:
        raise ValueError("v2 existing evidence fields are invalid")
    encoded_body = candidate_evidence.get("body_base64")
    if not isinstance(encoded_body, str):
        raise ValueError("v2 candidate body is missing")
    try:
        candidate_body = base64.b64decode(encoded_body, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("v2 candidate body is not strict base64") from exc
    if (
        hashlib.sha256(candidate_body).hexdigest() != candidate_sha256
        or candidate_evidence.get("body_sha256") != candidate_sha256
    ):
        raise ValueError("v2 candidate body digest does not match the conflict")
    candidate_object = decode_strict_json_object(
        candidate_body,
        label="Schema-v2 conflict candidate result",
    )
    candidate = ScrapeResult.model_validate(candidate_object)
    if candidate.item_id != item_id or candidate.run_id != run_id:
        raise ValueError("v2 candidate result identity is invalid")
    if candidate.status not in {ScrapeStatus.SUCCESS, ScrapeStatus.NO_RESULTS}:
        raise ValueError("v2 candidate result is not conclusive")
    if candidate.is_soft_blocked or candidate.is_network_error:
        raise ValueError("v2 candidate result carries a retry hint")
    if record.get("candidate_status") != candidate.status.value:
        raise ValueError("v2 candidate status does not match retained evidence")
    candidate_observation = semantic_observation(candidate)
    canonical_observation = semantic_observation(canonical)
    if candidate_evidence.get("result") != candidate.model_dump(mode="json"):
        raise ValueError("v2 full candidate evidence does not match its body")
    if candidate_evidence.get("semantic_observation") != candidate_observation:
        raise ValueError("v2 candidate semantic projection is invalid")
    if existing_evidence.get("body_sha256") != record.get("existing_sha256"):
        raise ValueError("v2 existing evidence digest is invalid")
    if existing_evidence.get("result") != canonical.model_dump(mode="json"):
        raise ValueError("v2 existing evidence does not match the canonical result")
    if existing_evidence.get("semantic_observation") != canonical_observation:
        raise ValueError("v2 existing semantic projection is invalid")
    expected_differences = sorted(
        field
        for field in SEMANTIC_OBSERVATION_FIELDS
        if canonical_observation.get(field) != candidate_observation.get(field)
    )
    if not expected_differences or record.get("differing_fields") != expected_differences:
        raise ValueError("v2 differing_fields does not match retained semantic evidence")


def _resolution_prefix(config: WorkerConfig, run_id: str) -> str:
    return f"{config.s3_scraper_prefix}/runs/{run_id}/{RESULT_CONFLICT_RESOLUTION_ROOT}/"


def _validate_resolution_record(
    body: bytes,
    record: dict[str, object],
    *,
    key: str,
    resolution_prefix: str,
    run_id: str,
    item_id: str,
    conflict_key: str,
    conflict_sha256: str,
    existing_sha256: str,
    candidate_sha256: str,
    candidate_status: str,
    differing_fields: tuple[str, ...],
    canonical_key: str,
    canonical_status: str,
) -> None:
    """Require a complete, content-addressed accept-canonical review record."""
    required_fields = {
        "schema_version",
        "resolution_type",
        "conflict_policy_version",
        "run_id",
        "item_id",
        "conflict_key",
        "conflict_evidence_sha256",
        "existing_sha256",
        "candidate_sha256",
        "candidate_status",
        "differing_fields",
        "canonical_result_key",
        "canonical_sha256",
        "canonical_status",
        "reviewed_at",
        "reviewed_by",
        "review_note",
    }
    if set(record) != required_fields:
        raise ValueError("resolution record fields are incomplete or unexpected")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ValueError("resolution schema version is invalid")
    if record["resolution_type"] != "accept-canonical":
        raise ValueError("resolution type is invalid")
    if (
        type(record["conflict_policy_version"]) is not int
        or record["conflict_policy_version"] != RESULT_CONFLICT_POLICY_VERSION
    ):
        raise ValueError("resolution conflict policy version is invalid")
    expected = {
        "run_id": run_id,
        "item_id": item_id,
        "conflict_key": conflict_key,
        "conflict_evidence_sha256": conflict_sha256,
        "existing_sha256": existing_sha256,
        "candidate_sha256": candidate_sha256,
        "candidate_status": candidate_status,
        "differing_fields": list(differing_fields),
        "canonical_result_key": canonical_key,
        "canonical_sha256": existing_sha256,
        "canonical_status": canonical_status,
    }
    if any(record.get(field) != value for field, value in expected.items()):
        raise ValueError("resolution record is not bound to the exact conflict/canonical body")
    for field in ("reviewed_by", "review_note"):
        review_value = record[field]
        if not isinstance(review_value, str) or not review_value.strip():
            raise ValueError(f"resolution {field} must be nonblank")
    reviewed_at = record["reviewed_at"]
    if not isinstance(reviewed_at, str):
        raise ValueError("resolution reviewed_at must be a timestamp")
    try:
        parsed_reviewed_at = datetime.fromisoformat(reviewed_at)
    except ValueError as exc:
        raise ValueError("resolution reviewed_at is invalid") from exc
    if parsed_reviewed_at.tzinfo is None or parsed_reviewed_at.utcoffset() is None:
        raise ValueError("resolution reviewed_at must include a timezone")

    resolution_sha256 = hashlib.sha256(body).hexdigest()
    expected_key = f"{resolution_prefix}v1/{conflict_sha256}/{resolution_sha256}.json"
    if key != expected_key:
        raise ValueError("resolution key does not match its content/conflict digest")


def write_accept_canonical_resolution(
    s3: S3Client,
    config: WorkerConfig,
    *,
    run_id: str,
    conflict_key: str,
    expected_conflict_sha256: str,
    expected_existing_sha256: str,
    expected_candidate_sha256: str,
    expected_candidate_status: ScrapeStatus,
    expected_differing_fields: tuple[str, ...],
    expected_canonical_sha256: str,
    expected_canonical_status: ScrapeStatus,
    reviewed_at: datetime,
    reviewed_by: str,
    review_note: str,
) -> str:
    """Conditionally append one explicit, fully bound accept-canonical review."""
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise ValueError("reviewed_at must include a timezone")
    if not reviewed_by.strip() or not review_note.strip():
        raise ValueError("reviewed_by and review_note must be nonblank")
    conflict_prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/result-conflicts/"
    if not conflict_key.startswith(conflict_prefix):
        raise ValueError("conflict key is outside the requested run")
    conflict_body = s3.get_object(Bucket=config.s3_bucket, Key=conflict_key)["Body"].read()
    conflict_sha256 = hashlib.sha256(conflict_body).hexdigest()
    if conflict_sha256 != expected_conflict_sha256:
        raise ValueError("conflict evidence body does not match the reviewed digest")
    conflict = decode_strict_json_object(conflict_body, label=f"Result conflict {conflict_key}")
    (
        item_id,
        existing_sha256,
        candidate_sha256,
        existing_status,
        candidate_status,
        differing_fields,
    ) = _validate_conflict_identity(
        conflict,
        run_id=run_id,
        prefix=conflict_prefix,
        key=conflict_key,
    )
    if existing_sha256 != expected_existing_sha256:
        raise ValueError("existing result digest does not match the reviewed value")
    if candidate_sha256 != expected_candidate_sha256:
        raise ValueError("candidate result digest does not match the reviewed value")
    if candidate_status != expected_candidate_status.value:
        raise ValueError("candidate status does not match the reviewed value")
    if differing_fields != expected_differing_fields:
        raise ValueError("differing fields do not match the reviewed value")
    if expected_canonical_sha256 != existing_sha256:
        raise ValueError("accepted canonical digest must equal the conflict's existing digest")
    if expected_canonical_status.value != existing_status:
        raise ValueError("accepted canonical status does not match the conflict")
    canonical_key, _, canonical = _read_canonical_result(
        s3,
        config,
        run_id=run_id,
        item_id=item_id,
        expected_sha256=expected_canonical_sha256,
        expected_status=expected_canonical_status.value,
    )
    if conflict["schema_version"] == 2:
        _validate_v2_conflict_evidence(
            conflict,
            run_id=run_id,
            item_id=item_id,
            candidate_sha256=candidate_sha256,
            canonical_key=canonical_key,
            canonical=canonical,
        )

    record = {
        "schema_version": _RESOLUTION_SCHEMA_VERSION,
        "resolution_type": "accept-canonical",
        "conflict_policy_version": RESULT_CONFLICT_POLICY_VERSION,
        "run_id": run_id,
        "item_id": item_id,
        "conflict_key": conflict_key,
        "conflict_evidence_sha256": conflict_sha256,
        "existing_sha256": existing_sha256,
        "candidate_sha256": candidate_sha256,
        "candidate_status": candidate_status,
        "differing_fields": list(differing_fields),
        "canonical_result_key": canonical_key,
        "canonical_sha256": expected_canonical_sha256,
        "canonical_status": canonical.status.value,
        "reviewed_at": reviewed_at.astimezone(UTC).isoformat(),
        "reviewed_by": reviewed_by.strip(),
        "review_note": review_note.strip(),
    }
    body = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    resolution_sha256 = hashlib.sha256(body).hexdigest()
    resolution_prefix = _resolution_prefix(config, run_id)
    key = f"{resolution_prefix}v1/{conflict_sha256}/{resolution_sha256}.json"
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except ClientError as exc:
        if str(exc.response.get("Error", {}).get("Code", "")) not in {
            "412",
            "PreconditionFailed",
        }:
            raise
        existing_body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        if existing_body != body:
            raise ValueError(
                "existing resolution object does not match its content address"
            ) from exc
    persisted_body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
    if persisted_body != body:
        raise ValueError("persisted resolution object failed exact readback verification")
    return key


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
        result_object = decode_strict_json_object(body, label=f"Result {key}")
        result = ScrapeResult.model_validate(result_object)
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


def audit_result_conflicts(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> ResultConflictReport:
    """Return conflict dispositions under explicit append-only review evidence."""
    conflict_prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/result-conflicts/"
    resolution_prefix = _resolution_prefix(config, run_id)
    decision_resolutions = read_terminal_candidate_resolutions(s3, config, run_id)
    decision_resolutions_by_candidate: dict[str, list[TerminalCandidateResolution]] = {}
    for resolution in decision_resolutions:
        decision_resolutions_by_candidate.setdefault(resolution.candidate_key, []).append(
            resolution
        )
    paginator = s3.get_paginator("list_objects_v2")
    conflict_keys: set[str] = set()
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=conflict_prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if isinstance(key, str) and key.startswith(conflict_prefix) and key != conflict_prefix:
                conflict_keys.add(key)

    resolution_keys: set[str] = set()
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=resolution_prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if (
                isinstance(key, str)
                and key.startswith(resolution_prefix)
                and key != resolution_prefix
            ):
                resolution_keys.add(key)

    if not conflict_keys and not resolution_keys:
        return ResultConflictReport.empty()

    resolved_keys: list[str] = []
    unresolved_keys: list[str] = []
    digest_entries: list[dict[str, object]] = []
    resolution_candidates: dict[
        str,
        list[tuple[str, bytes | None, dict[str, object] | None]],
    ] = {}
    invalid_resolution_keys: set[str] = set()
    consumed_resolution_keys: set[str] = set()
    for key in sorted(resolution_keys):
        body: bytes | None
        record: dict[str, object] | None
        try:
            body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        except Exception:
            body = None
            record = None
        else:
            try:
                record = decode_strict_json_object(body, label=f"Conflict resolution {key}")
            except ValueError:
                record = None
        evidence_sha256 = hashlib.sha256(body).hexdigest() if body is not None else None
        digest_entries.append(
            {
                "kind": "resolution",
                "key": key,
                "evidence_sha256": evidence_sha256,
                "readable_strict_json": record is not None,
            }
        )
        relative_key = key.removeprefix(resolution_prefix)
        parts = relative_key.split("/")
        if len(parts) == 3 and parts[0] == "v1" and _is_sha256(parts[1]):
            resolution_candidates.setdefault(parts[1], []).append((key, body, record))
        else:
            invalid_resolution_keys.add(key)
        if body is None or record is None:
            invalid_resolution_keys.add(key)

    for key in sorted(conflict_keys):
        try:
            conflict_body = s3.get_object(
                Bucket=config.s3_bucket,
                Key=key,
            )["Body"].read()
        except Exception:
            unresolved_keys.append(key)
            digest_entries.append(
                {
                    "key": key,
                    "kind": "conflict",
                    "evidence_sha256": None,
                    "disposition": "unresolved",
                    "reason": "conflict evidence cannot be read",
                }
            )
            continue

        evidence_sha256 = hashlib.sha256(conflict_body).hexdigest()
        try:
            conflict = decode_strict_json_object(
                conflict_body,
                label=f"Result conflict {key}",
            )
            (
                item_id,
                existing_sha256,
                candidate_sha256,
                existing_status,
                candidate_status,
                differing_fields,
            ) = _validate_conflict_identity(
                conflict,
                run_id=run_id,
                prefix=conflict_prefix,
                key=key,
            )
            canonical_key, canonical_body, canonical = _read_canonical_result(
                s3,
                config,
                run_id=run_id,
                item_id=item_id,
                expected_sha256=existing_sha256,
                expected_status=existing_status,
            )
            if conflict["schema_version"] == 2:
                _validate_v2_conflict_evidence(
                    conflict,
                    run_id=run_id,
                    item_id=item_id,
                    candidate_sha256=candidate_sha256,
                    canonical_key=canonical_key,
                    canonical=canonical,
                )
        except (KeyError, TypeError, ValueError, ClientError):
            resolved = False
            reason = "conflict or canonical evidence is invalid"
            canonical_sha256 = None
            candidate_resolution_keys: list[str] = []
        else:
            canonical_sha256 = hashlib.sha256(canonical_body).hexdigest()
            candidates = resolution_candidates.get(evidence_sha256, [])
            candidate_resolution_keys = [candidate[0] for candidate in candidates]
            resolution_errors = 0
            for resolution_key, resolution_body, resolution in candidates:
                consumed_resolution_keys.add(resolution_key)
                if resolution_body is None or resolution is None:
                    resolution_errors += 1
                    invalid_resolution_keys.add(resolution_key)
                    continue
                try:
                    _validate_resolution_record(
                        resolution_body,
                        resolution,
                        key=resolution_key,
                        resolution_prefix=resolution_prefix,
                        run_id=run_id,
                        item_id=item_id,
                        conflict_key=key,
                        conflict_sha256=evidence_sha256,
                        existing_sha256=existing_sha256,
                        candidate_sha256=candidate_sha256,
                        candidate_status=candidate_status,
                        differing_fields=differing_fields,
                        canonical_key=canonical_key,
                        canonical_status=canonical.status.value,
                    )
                except ValueError:
                    resolution_errors += 1
                    invalid_resolution_keys.add(resolution_key)
            explicit_conflict_review = bool(candidates) and resolution_errors == 0
            journal_candidate_key = (
                f"{config.s3_scraper_prefix}/runs/{run_id}/terminal-candidates/v1/"
                f"{hashlib.sha256(item_id.encode()).hexdigest()}/result/"
                f"{candidate_sha256}.json"
            )
            decision_reviews = (
                [
                    resolution
                    for resolution in decision_resolutions_by_candidate.get(
                        journal_candidate_key,
                        [],
                    )
                    if resolution.decision_kind == "result"
                    and resolution.canonical_key == canonical_key
                    and resolution.canonical_sha256 == canonical_sha256
                    and resolution.candidate_sha256 == candidate_sha256
                ]
                if conflict["schema_version"] == 2
                else []
            )
            candidate_resolution_keys.extend(resolution.key for resolution in decision_reviews)
            resolved = explicit_conflict_review or bool(decision_reviews)
            reason = (
                "explicit canonical decision review is valid"
                if resolved
                else "missing or invalid explicit canonical review"
            )

        digest_entries.append(
            {
                "kind": "conflict",
                "key": key,
                "evidence_sha256": evidence_sha256,
                "canonical_sha256": canonical_sha256,
                "resolution_keys": candidate_resolution_keys,
                "disposition": "resolved" if resolved else "unresolved",
                "reason": reason,
            }
        )
        if resolved:
            resolved_keys.append(key)
            logger.warning(
                "Accepted canonical result under explicit conflict review: {}",
                key,
            )
        else:
            unresolved_keys.append(key)

    invalid_resolution_keys.update(resolution_keys - consumed_resolution_keys)

    report = ResultConflictReport(
        conflict_policy_version=RESULT_CONFLICT_POLICY_VERSION,
        total_count=len(conflict_keys),
        resolved_count=len(resolved_keys),
        unresolved_count=len(unresolved_keys),
        evidence_sha256=_result_conflict_evidence_digest(digest_entries),
        resolved_keys=tuple(resolved_keys),
        unresolved_keys=tuple(unresolved_keys),
        invalid_resolution_count=len(invalid_resolution_keys),
        invalid_resolution_keys=tuple(sorted(invalid_resolution_keys)),
    )

    return report


def require_no_result_conflicts(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> ResultConflictReport:
    """Fail closed on unresolved conflicts and return the audited inventory."""
    try:
        report = audit_result_conflicts(s3, config, run_id)
    except CandidateJournalError as exc:
        raise RunResultConflictError(
            f"Run {run_id} has invalid terminal-decision resolution evidence; "
            "refusing to aggregate or publish this run."
        ) from exc

    blocking_keys = report.unresolved_keys + report.invalid_resolution_keys
    if blocking_keys:
        sample = ", ".join(blocking_keys[:10])
        remainder = len(blocking_keys) - 10
        suffix = f" (and {remainder} more)" if remainder > 0 else ""
        raise RunResultConflictError(
            f"Run {run_id} has {report.unresolved_count} unresolved durable result "
            f"conflict(s), {report.invalid_resolution_count} invalid/orphan resolution "
            f"object(s) ({report.resolved_count} explicitly reviewed): "
            f"{sample}{suffix}. Refusing to aggregate or publish this run."
        )
    return report


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
