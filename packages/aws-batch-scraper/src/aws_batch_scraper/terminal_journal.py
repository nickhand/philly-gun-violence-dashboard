"""Append-only terminal observations that survive canonical publication races."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from typing import Literal, TypeGuard, cast

from mypy_boto3_s3.client import S3Client

from aws_batch_scraper.config import WorkerConfig
from aws_batch_scraper.result_semantics import semantic_observation
from aws_batch_scraper.strict_json import decode_strict_json_object
from aws_batch_scraper.types import ScrapeResult, ScrapeStatus

JOURNAL_SCHEMA_VERSION = 1
DISPOSITION_SCHEMA_VERSION = 1
DECISION_SCHEMA_VERSION = 1
RESOLUTION_SCHEMA_VERSION = 1
# This namespace is a security boundary: production IAM must grant workers and
# workflow automation read access only. Human operators are the sole writers.
TERMINAL_DECISION_RESOLUTION_PATH = "terminal-decision-resolutions/v1"
TerminalKind = Literal["result", "failure"]
DispositionOutcome = Literal["created", "duplicate", "conflict"]
_CANDIDATE_FIELDS = frozenset(
    {
        "schema_version",
        "recorded_at",
        "run_id",
        "item_id",
        "kind",
        "candidate_sha256",
        "observation_sha256",
        "candidate_body_base64",
        "sqs_delivery",
    }
)
_DISPOSITION_FIELDS = frozenset(
    {
        "schema_version",
        "recorded_at",
        "run_id",
        "item_id",
        "message_id",
        "message_body_sha256",
        "receive_count",
        "kind",
        "outcome",
        "candidate_key",
        "candidate_sha256",
        "candidate_observation_sha256",
        "canonical_key",
        "canonical_sha256",
        "canonical_observation_sha256",
        "conflict_evidence_key",
    }
)
_DECISION_FIELDS = frozenset(
    {
        "schema_version",
        "decided_at",
        "run_id",
        "item_id",
        "kind",
        "candidate_key",
        "candidate_sha256",
        "candidate_observation_sha256",
        "canonical_key",
    }
)
_DECISION_CONFLICT_FIELDS = frozenset(
    {
        "schema_version",
        "recorded_at",
        "terminal_status",
        "run_id",
        "item_id",
        "decision_key",
        "decision_kind",
        "decision_candidate_key",
        "decision_candidate_sha256",
        "decision_observation_sha256",
        "candidate_kind",
        "candidate_key",
        "candidate_sha256",
        "candidate_observation_sha256",
    }
)
_CANDIDATE_RESOLUTION_FIELDS = frozenset(
    {
        "schema_version",
        "policy_version",
        "resolution_type",
        "reviewed_at",
        "reviewed_by",
        "review_note",
        "run_id",
        "item_id",
        "decision_key",
        "decision_sha256",
        "decision_kind",
        "decision_candidate_key",
        "decision_candidate_sha256",
        "decision_candidate_observation_sha256",
        "canonical_key",
        "canonical_sha256",
        "canonical_observation_sha256",
        "canonical_status",
        "rejected_candidate_key",
        "rejected_candidate_kind",
        "rejected_candidate_sha256",
        "rejected_candidate_observation_sha256",
    }
)
_DELIVERY_FIELDS = frozenset({"message_id", "md5_of_body", "body_sha256", "system_attributes"})
_SYSTEM_ATTRIBUTE_FIELDS = frozenset(
    {
        "ApproximateFirstReceiveTimestamp",
        "ApproximateReceiveCount",
        "SenderId",
        "SentTimestamp",
        "SequenceNumber",
    }
)


class CandidateJournalError(RuntimeError):
    """Raised when append-only candidate evidence cannot be trusted."""


@dataclass(frozen=True)
class TerminalCandidate:
    """One content-addressed exact-run terminal observation."""

    key: str
    run_id: str
    item_id: str
    kind: TerminalKind
    candidate_sha256: str
    observation_sha256: str
    candidate_body: bytes
    result: ScrapeResult
    delivery_metadata: dict[str, object] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class TerminalDisposition:
    """Durable outcome for one stable SQS message delivery identity."""

    key: str
    run_id: str
    item_id: str
    message_id: str
    message_body_sha256: str
    receive_count: int
    kind: TerminalKind
    outcome: DispositionOutcome
    candidate_key: str
    candidate_sha256: str
    candidate_observation_sha256: str
    canonical_key: str
    canonical_sha256: str
    canonical_observation_sha256: str | None
    conflict_evidence_key: str | None


@dataclass(frozen=True)
class TerminalDecision:
    """The first terminal candidate authorized to materialize compatibility state."""

    key: str
    body_sha256: str
    run_id: str
    item_id: str
    kind: TerminalKind
    canonical_key: str
    candidate: TerminalCandidate


@dataclass(frozen=True)
class TerminalDecisionConflict:
    """Append-only evidence that a losing candidate chose another terminal kind."""

    key: str
    run_id: str
    item_id: str
    decision_key: str
    decision_kind: TerminalKind
    decision_candidate_sha256: str
    candidate_kind: TerminalKind
    candidate_key: str
    candidate_sha256: str


@dataclass(frozen=True)
class TerminalCandidateResolution:
    """Explicit human review accepting one exact terminal decision over a candidate."""

    key: str
    body_sha256: str
    run_id: str
    item_id: str
    decision_key: str
    decision_sha256: str
    decision_kind: TerminalKind
    decision_candidate_sha256: str
    canonical_key: str
    canonical_sha256: str
    candidate_key: str
    candidate_kind: TerminalKind
    candidate_sha256: str


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _is_sha256(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_timestamp(value: object, *, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise CandidateJournalError(f"{label} has an invalid recorded_at timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CandidateJournalError(f"{label} has an invalid recorded_at timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CandidateJournalError(f"{label} recorded_at must include a timezone")


def _observation_body(result: ScrapeResult) -> bytes:
    return json.dumps(
        semantic_observation(result),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _candidate_key(
    config: WorkerConfig,
    run_id: str,
    item_id: str,
    kind: TerminalKind,
    candidate_sha256: str,
) -> str:
    item_token = _sha256(item_id.encode())
    return (
        f"{config.s3_scraper_prefix}/runs/{run_id}/terminal-candidates/v1/"
        f"{item_token}/{kind}/{candidate_sha256}.json"
    )


def _decision_key(config: WorkerConfig, run_id: str, item_id: str) -> str:
    return (
        f"{config.s3_scraper_prefix}/runs/{run_id}/terminal-decisions/v1/"
        f"{_sha256(item_id.encode())}.json"
    )


def _validate_delivery_metadata(delivery: object, *, label: str) -> dict[str, object]:
    if not isinstance(delivery, dict) or any(field not in _DELIVERY_FIELDS for field in delivery):
        raise CandidateJournalError(f"{label} has unsafe delivery metadata")
    for field in ("message_id", "md5_of_body", "body_sha256"):
        value = delivery.get(field)
        if value is not None and (not isinstance(value, str) or not value):
            raise CandidateJournalError(f"{label} has an invalid {field}")
    system_attributes = delivery.get("system_attributes")
    if system_attributes is not None and (
        not isinstance(system_attributes, dict)
        or any(field not in _SYSTEM_ATTRIBUTE_FIELDS for field in system_attributes)
        or any(not isinstance(value, str) for value in system_attributes.values())
    ):
        raise CandidateJournalError(f"{label} has unsafe SQS system attributes")
    return delivery


def _validate_candidate_result(
    result: ScrapeResult,
    *,
    run_id: str,
    item_id: str,
    kind: TerminalKind,
) -> None:
    if result.run_id != run_id or result.item_id != item_id:
        raise CandidateJournalError("Terminal candidate identity does not match its envelope")
    if result.is_soft_blocked or result.is_network_error:
        raise CandidateJournalError("Terminal candidate contains a retry hint")
    allowed = (
        {ScrapeStatus.SUCCESS, ScrapeStatus.NO_RESULTS}
        if kind == "result"
        else {ScrapeStatus.FAILED, ScrapeStatus.INVALID_INPUT}
    )
    if result.status not in allowed:
        raise CandidateJournalError(
            f"Terminal candidate kind {kind!r} cannot contain status {result.status.value}"
        )


def _decode_candidate(
    body: bytes,
    *,
    key: str,
    expected_prefix: str,
) -> TerminalCandidate:
    try:
        record = decode_strict_json_object(body, label=f"Terminal candidate {key}")
    except ValueError as exc:
        raise CandidateJournalError(str(exc)) from exc
    if set(record) != _CANDIDATE_FIELDS:
        raise CandidateJournalError(f"Terminal candidate {key} fields are incomplete or unexpected")
    schema_version = record.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != JOURNAL_SCHEMA_VERSION
    ):
        raise CandidateJournalError(f"Terminal candidate {key} has an unsupported schema")
    _validate_timestamp(record.get("recorded_at"), label=f"Terminal candidate {key}")
    run_id = record.get("run_id")
    item_id = record.get("item_id")
    kind = record.get("kind")
    candidate_sha256 = record.get("candidate_sha256")
    observation_sha256 = record.get("observation_sha256")
    candidate_body_base64 = record.get("candidate_body_base64")
    delivery = record.get("sqs_delivery")
    if not isinstance(run_id, str) or not run_id:
        raise CandidateJournalError(f"Terminal candidate {key} has an invalid run ID")
    if not isinstance(item_id, str) or not item_id:
        raise CandidateJournalError(f"Terminal candidate {key} has an invalid item ID")
    if kind not in {"result", "failure"}:
        raise CandidateJournalError(f"Terminal candidate {key} has an invalid kind")
    if not _is_sha256(candidate_sha256):
        raise CandidateJournalError(f"Terminal candidate {key} has an invalid body digest")
    if not _is_sha256(observation_sha256):
        raise CandidateJournalError(f"Terminal candidate {key} has an invalid observation digest")
    if not isinstance(candidate_body_base64, str):
        raise CandidateJournalError(f"Terminal candidate {key} lacks its candidate body")
    safe_delivery = _validate_delivery_metadata(delivery, label=f"Terminal candidate {key}")
    try:
        candidate_body = base64.b64decode(candidate_body_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise CandidateJournalError(f"Terminal candidate {key} has invalid base64") from exc
    if _sha256(candidate_body) != candidate_sha256:
        raise CandidateJournalError(f"Terminal candidate {key} body digest does not match")
    try:
        candidate_object = decode_strict_json_object(
            candidate_body,
            label=f"Terminal candidate body {key}",
        )
        expected_result_fields = set(ScrapeResult.model_fields)
        if kind == "failure":
            expected_result_fields.add("failed_at")
        if set(candidate_object) != expected_result_fields:
            raise ValueError("candidate body fields are incomplete or unexpected")
        result = ScrapeResult.model_validate(candidate_object)
    except ValueError as exc:
        raise CandidateJournalError(f"Terminal candidate {key} body is invalid") from exc
    typed_kind = cast(TerminalKind, kind)
    _validate_candidate_result(result, run_id=run_id, item_id=item_id, kind=typed_kind)
    if _sha256(_observation_body(result)) != observation_sha256:
        raise CandidateJournalError(
            f"Terminal candidate {key} semantic observation digest does not match"
        )

    item_token = _sha256(item_id.encode())
    expected_key = f"{expected_prefix}{item_token}/{typed_kind}/{candidate_sha256}.json"
    if key != expected_key:
        raise CandidateJournalError(f"Terminal candidate {key} does not match its key identity")
    return TerminalCandidate(
        key=key,
        run_id=run_id,
        item_id=item_id,
        kind=typed_kind,
        candidate_sha256=candidate_sha256,
        observation_sha256=observation_sha256,
        candidate_body=candidate_body,
        result=result,
        delivery_metadata=dict(safe_delivery),
    )


def _decode_decision(
    s3: S3Client,
    config: WorkerConfig,
    body: bytes,
    *,
    key: str,
) -> TerminalDecision:
    try:
        record = decode_strict_json_object(body, label=f"Terminal decision {key}")
    except ValueError as exc:
        raise CandidateJournalError(str(exc)) from exc
    if set(record) != _DECISION_FIELDS:
        raise CandidateJournalError(f"Terminal decision {key} fields are incomplete or unexpected")
    schema_version = record.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != DECISION_SCHEMA_VERSION
    ):
        raise CandidateJournalError(f"Terminal decision {key} has an unsupported schema")
    _validate_timestamp(record.get("decided_at"), label=f"Terminal decision {key}")
    run_id = record.get("run_id")
    item_id = record.get("item_id")
    kind = record.get("kind")
    candidate_key = record.get("candidate_key")
    candidate_sha256 = record.get("candidate_sha256")
    candidate_observation_sha256 = record.get("candidate_observation_sha256")
    canonical_key = record.get("canonical_key")
    if not isinstance(run_id, str) or not run_id:
        raise CandidateJournalError(f"Terminal decision {key} has an invalid run ID")
    if not isinstance(item_id, str) or not item_id:
        raise CandidateJournalError(f"Terminal decision {key} has an invalid item ID")
    if kind not in {"result", "failure"}:
        raise CandidateJournalError(f"Terminal decision {key} has an invalid kind")
    if not isinstance(candidate_key, str) or not candidate_key:
        raise CandidateJournalError(f"Terminal decision {key} has an invalid candidate key")
    if not _is_sha256(candidate_sha256) or not _is_sha256(candidate_observation_sha256):
        raise CandidateJournalError(f"Terminal decision {key} has invalid candidate digests")
    expected_canonical_key = (
        f"{config.s3_scraper_prefix}/runs/{run_id}/"
        f"{'results' if kind == 'result' else 'failures'}/{item_id}.json"
    )
    if not isinstance(canonical_key, str) or canonical_key != expected_canonical_key:
        raise CandidateJournalError(f"Terminal decision {key} has an invalid canonical key")
    if key != _decision_key(config, run_id, item_id):
        raise CandidateJournalError(f"Terminal decision {key} does not match its key identity")
    candidate_body = s3.get_object(
        Bucket=config.s3_bucket,
        Key=candidate_key,
    )["Body"].read()
    candidate = _decode_candidate(
        candidate_body,
        key=candidate_key,
        expected_prefix=(f"{config.s3_scraper_prefix}/runs/{run_id}/terminal-candidates/v1/"),
    )
    typed_kind = cast(TerminalKind, kind)
    if (
        candidate.run_id != run_id
        or candidate.item_id != item_id
        or candidate.kind != typed_kind
        or candidate.candidate_sha256 != candidate_sha256
        or candidate.observation_sha256 != candidate_observation_sha256
    ):
        raise CandidateJournalError(
            f"Terminal decision {key} does not match its retained candidate"
        )
    return TerminalDecision(
        key=key,
        body_sha256=_sha256(body),
        run_id=run_id,
        item_id=item_id,
        kind=typed_kind,
        canonical_key=canonical_key,
        candidate=candidate,
    )


def claim_terminal_decision(
    s3: S3Client,
    config: WorkerConfig,
    *,
    candidate: TerminalCandidate,
) -> TerminalDecision:
    """CAS one terminal candidate into the run/item's single decision envelope."""
    key = _decision_key(config, candidate.run_id, candidate.item_id)
    canonical_key = (
        f"{config.s3_scraper_prefix}/runs/{candidate.run_id}/"
        f"{'results' if candidate.kind == 'result' else 'failures'}/"
        f"{candidate.item_id}.json"
    )
    record = {
        "schema_version": DECISION_SCHEMA_VERSION,
        "decided_at": datetime.now(UTC).isoformat(),
        "run_id": candidate.run_id,
        "item_id": candidate.item_id,
        "kind": candidate.kind,
        "candidate_key": candidate.key,
        "candidate_sha256": candidate.candidate_sha256,
        "candidate_observation_sha256": candidate.observation_sha256,
        "canonical_key": canonical_key,
    }
    body = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    put_succeeded = False
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            IfNoneMatch="*",
        )
        put_succeeded = True
    except Exception as exc:
        put_error = exc
    else:
        put_error = None
    try:
        observed = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        decision = _decode_decision(s3, config, observed, key=key)
    except Exception as exc:
        raise CandidateJournalError(
            f"Could not durably claim terminal decision for run={candidate.run_id}, "
            f"item={candidate.item_id}"
        ) from (put_error or exc)
    if put_succeeded and observed != body:
        raise CandidateJournalError(
            f"Terminal decision readback mismatch for run={candidate.run_id}, "
            f"item={candidate.item_id}"
        )
    return decision


def read_terminal_decisions(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> tuple[TerminalDecision, ...]:
    """Read and validate every first-writer terminal decision for one run."""
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/terminal-decisions/v1/"
    paginator = s3.get_paginator("list_objects_v2")
    keys: set[str] = set()
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if isinstance(key, str) and key.startswith(prefix):
                keys.add(key)
    decisions: list[TerminalDecision] = []
    for key in sorted(keys):
        if not key.endswith(".json"):
            raise CandidateJournalError(f"Unexpected non-JSON terminal decision object {key}")
        body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        decision = _decode_decision(s3, config, body, key=key)
        if decision.run_id != run_id:
            raise CandidateJournalError(f"Terminal decision {key} belongs to another run")
        decisions.append(decision)
    return tuple(decisions)


def _decision_conflict_key(
    config: WorkerConfig,
    run_id: str,
    item_id: str,
    candidate_sha256: str,
) -> str:
    return (
        f"{config.s3_scraper_prefix}/runs/{run_id}/terminal-decision-conflicts/v1/"
        f"{_sha256(item_id.encode())}/{candidate_sha256}.json"
    )


def _decode_decision_conflict(
    s3: S3Client,
    config: WorkerConfig,
    body: bytes,
    *,
    key: str,
) -> TerminalDecisionConflict:
    try:
        record = decode_strict_json_object(
            body,
            label=f"Terminal decision conflict {key}",
        )
    except ValueError as exc:
        raise CandidateJournalError(str(exc)) from exc
    if set(record) != _DECISION_CONFLICT_FIELDS:
        raise CandidateJournalError(
            f"Terminal decision conflict {key} fields are incomplete or unexpected"
        )
    schema_version = record.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 1
    ):
        raise CandidateJournalError(f"Terminal decision conflict {key} has an unsupported schema")
    if record.get("terminal_status") != "terminal-decision-conflict":
        raise CandidateJournalError(
            f"Terminal decision conflict {key} has an invalid terminal status"
        )
    _validate_timestamp(
        record.get("recorded_at"),
        label=f"Terminal decision conflict {key}",
    )
    run_id = record.get("run_id")
    item_id = record.get("item_id")
    decision_key = record.get("decision_key")
    decision_kind = record.get("decision_kind")
    decision_candidate_key = record.get("decision_candidate_key")
    decision_candidate_sha256 = record.get("decision_candidate_sha256")
    decision_observation_sha256 = record.get("decision_observation_sha256")
    candidate_kind = record.get("candidate_kind")
    candidate_key = record.get("candidate_key")
    candidate_sha256 = record.get("candidate_sha256")
    candidate_observation_sha256 = record.get("candidate_observation_sha256")
    for label, value in (
        ("run ID", run_id),
        ("item ID", item_id),
        ("decision key", decision_key),
        ("decision candidate key", decision_candidate_key),
        ("candidate key", candidate_key),
    ):
        if not isinstance(value, str) or not value:
            raise CandidateJournalError(f"Terminal decision conflict {key} has an invalid {label}")
    if decision_kind not in {"result", "failure"} or candidate_kind not in {
        "result",
        "failure",
    }:
        raise CandidateJournalError(f"Terminal decision conflict {key} has an invalid kind")
    if decision_kind == candidate_kind:
        raise CandidateJournalError(
            f"Terminal decision conflict {key} does not cross terminal kinds"
        )
    for label, value in (
        ("decision candidate digest", decision_candidate_sha256),
        ("decision observation digest", decision_observation_sha256),
        ("candidate digest", candidate_sha256),
        ("candidate observation digest", candidate_observation_sha256),
    ):
        if not _is_sha256(value):
            raise CandidateJournalError(f"Terminal decision conflict {key} has an invalid {label}")
    typed_run_id = cast(str, run_id)
    typed_item_id = cast(str, item_id)
    typed_decision_key = cast(str, decision_key)
    typed_candidate_key = cast(str, candidate_key)
    typed_decision_candidate_sha256 = cast(str, decision_candidate_sha256)
    typed_candidate_sha256 = cast(str, candidate_sha256)
    if key != _decision_conflict_key(
        config,
        typed_run_id,
        typed_item_id,
        typed_candidate_sha256,
    ):
        raise CandidateJournalError(
            f"Terminal decision conflict {key} does not match its key identity"
        )
    decision_body = s3.get_object(
        Bucket=config.s3_bucket,
        Key=typed_decision_key,
    )["Body"].read()
    decision = _decode_decision(
        s3,
        config,
        decision_body,
        key=typed_decision_key,
    )
    candidate_body = s3.get_object(
        Bucket=config.s3_bucket,
        Key=typed_candidate_key,
    )["Body"].read()
    candidate = _decode_candidate(
        candidate_body,
        key=typed_candidate_key,
        expected_prefix=(f"{config.s3_scraper_prefix}/runs/{run_id}/terminal-candidates/v1/"),
    )
    if (
        decision.run_id != run_id
        or decision.item_id != item_id
        or decision.kind != decision_kind
        or decision.candidate.key != decision_candidate_key
        or decision.candidate.candidate_sha256 != decision_candidate_sha256
        or decision.candidate.observation_sha256 != decision_observation_sha256
        or candidate.run_id != run_id
        or candidate.item_id != item_id
        or candidate.kind != candidate_kind
        or candidate.candidate_sha256 != candidate_sha256
        or candidate.observation_sha256 != candidate_observation_sha256
    ):
        raise CandidateJournalError(
            f"Terminal decision conflict {key} does not match retained evidence"
        )
    return TerminalDecisionConflict(
        key=key,
        run_id=typed_run_id,
        item_id=typed_item_id,
        decision_key=typed_decision_key,
        decision_kind=cast(TerminalKind, decision_kind),
        decision_candidate_sha256=typed_decision_candidate_sha256,
        candidate_kind=cast(TerminalKind, candidate_kind),
        candidate_key=typed_candidate_key,
        candidate_sha256=typed_candidate_sha256,
    )


def write_terminal_decision_conflict(
    s3: S3Client,
    config: WorkerConfig,
    *,
    decision: TerminalDecision,
    candidate: TerminalCandidate,
) -> TerminalDecisionConflict:
    """Preserve a losing cross-kind candidate under first-decision policy."""
    if (
        decision.run_id != candidate.run_id
        or decision.item_id != candidate.item_id
        or decision.kind == candidate.kind
    ):
        raise CandidateJournalError("Terminal decision conflict identity is invalid")
    key = _decision_conflict_key(
        config,
        candidate.run_id,
        candidate.item_id,
        candidate.candidate_sha256,
    )
    record = {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "terminal_status": "terminal-decision-conflict",
        "run_id": candidate.run_id,
        "item_id": candidate.item_id,
        "decision_key": decision.key,
        "decision_kind": decision.kind,
        "decision_candidate_key": decision.candidate.key,
        "decision_candidate_sha256": decision.candidate.candidate_sha256,
        "decision_observation_sha256": decision.candidate.observation_sha256,
        "candidate_kind": candidate.kind,
        "candidate_key": candidate.key,
        "candidate_sha256": candidate.candidate_sha256,
        "candidate_observation_sha256": candidate.observation_sha256,
    }
    body = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except Exception as exc:
        put_error = exc
    else:
        put_error = None
    try:
        observed = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        conflict = _decode_decision_conflict(s3, config, observed, key=key)
    except Exception as exc:
        raise CandidateJournalError(
            f"Could not durably commit terminal decision conflict for "
            f"run={candidate.run_id}, item={candidate.item_id}"
        ) from (put_error or exc)
    if put_error is None and observed != body:
        raise CandidateJournalError(
            f"Terminal decision conflict readback mismatch for run={candidate.run_id}, "
            f"item={candidate.item_id}"
        )
    return conflict


def read_terminal_decision_conflicts(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> tuple[TerminalDecisionConflict, ...]:
    """Read and validate every cross-kind losing-candidate record for a run."""
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/terminal-decision-conflicts/v1/"
    paginator = s3.get_paginator("list_objects_v2")
    keys: set[str] = set()
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if isinstance(key, str) and key.startswith(prefix):
                keys.add(key)
    conflicts: list[TerminalDecisionConflict] = []
    for key in sorted(keys):
        if not key.endswith(".json"):
            raise CandidateJournalError(
                f"Unexpected non-JSON terminal decision conflict object {key}"
            )
        body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        conflict = _decode_decision_conflict(s3, config, body, key=key)
        if conflict.run_id != run_id:
            raise CandidateJournalError(f"Terminal decision conflict {key} belongs to another run")
        conflicts.append(conflict)
    return tuple(conflicts)


def _candidate_resolution_prefix(config: WorkerConfig, run_id: str) -> str:
    return f"{config.s3_scraper_prefix}/runs/{run_id}/{TERMINAL_DECISION_RESOLUTION_PATH}/"


def _decode_candidate_resolution(
    s3: S3Client,
    config: WorkerConfig,
    body: bytes,
    *,
    key: str,
    expected_run_id: str,
) -> TerminalCandidateResolution:
    try:
        record = decode_strict_json_object(
            body,
            label=f"Terminal candidate resolution {key}",
        )
    except ValueError as exc:
        raise CandidateJournalError(str(exc)) from exc
    if set(record) != _CANDIDATE_RESOLUTION_FIELDS:
        raise CandidateJournalError(
            f"Terminal candidate resolution {key} fields are incomplete or unexpected"
        )
    schema_version = record.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != RESOLUTION_SCHEMA_VERSION
    ):
        raise CandidateJournalError(
            f"Terminal candidate resolution {key} has an unsupported schema"
        )
    policy_version = record.get("policy_version")
    if (
        not isinstance(policy_version, int)
        or isinstance(policy_version, bool)
        or policy_version != 1
    ):
        raise CandidateJournalError(
            f"Terminal candidate resolution {key} has an unsupported policy"
        )
    if record.get("resolution_type") != "accept-decision":
        raise CandidateJournalError(
            f"Terminal candidate resolution {key} has an invalid resolution type"
        )
    _validate_timestamp(
        record.get("reviewed_at"),
        label=f"Terminal candidate resolution {key}",
    )
    for field in ("reviewed_by", "review_note"):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CandidateJournalError(
                f"Terminal candidate resolution {key} has an invalid {field}"
            )

    run_id = record.get("run_id")
    item_id = record.get("item_id")
    decision_key = record.get("decision_key")
    decision_sha256 = record.get("decision_sha256")
    decision_kind = record.get("decision_kind")
    decision_candidate_key = record.get("decision_candidate_key")
    decision_candidate_sha256 = record.get("decision_candidate_sha256")
    decision_candidate_observation_sha256 = record.get("decision_candidate_observation_sha256")
    canonical_key = record.get("canonical_key")
    canonical_sha256 = record.get("canonical_sha256")
    canonical_observation_sha256 = record.get("canonical_observation_sha256")
    canonical_status = record.get("canonical_status")
    candidate_key = record.get("rejected_candidate_key")
    candidate_kind = record.get("rejected_candidate_kind")
    candidate_sha256 = record.get("rejected_candidate_sha256")
    candidate_observation_sha256 = record.get("rejected_candidate_observation_sha256")
    for label, value in (
        ("run ID", run_id),
        ("item ID", item_id),
        ("decision key", decision_key),
        ("decision candidate key", decision_candidate_key),
        ("canonical key", canonical_key),
        ("candidate key", candidate_key),
        ("canonical status", canonical_status),
    ):
        if not isinstance(value, str) or not value:
            raise CandidateJournalError(
                f"Terminal candidate resolution {key} has an invalid {label}"
            )
    for label, value in (
        ("decision digest", decision_sha256),
        ("decision candidate digest", decision_candidate_sha256),
        ("decision candidate observation digest", decision_candidate_observation_sha256),
        ("canonical digest", canonical_sha256),
        ("canonical observation digest", canonical_observation_sha256),
        ("candidate digest", candidate_sha256),
        ("candidate observation digest", candidate_observation_sha256),
    ):
        if not _is_sha256(value):
            raise CandidateJournalError(
                f"Terminal candidate resolution {key} has an invalid {label}"
            )
    if run_id != expected_run_id:
        raise CandidateJournalError(f"Terminal candidate resolution {key} belongs to another run")
    if decision_kind not in {"result", "failure"} or candidate_kind not in {
        "result",
        "failure",
    }:
        raise CandidateJournalError(
            f"Terminal candidate resolution {key} has an invalid terminal kind"
        )
    typed_run_id = cast(str, run_id)
    typed_item_id = cast(str, item_id)
    typed_decision_key = cast(str, decision_key)
    typed_candidate_key = cast(str, candidate_key)
    resolution_prefix = _candidate_resolution_prefix(config, typed_run_id)
    expected_key = (
        f"{resolution_prefix}{_sha256(typed_item_id.encode())}/{decision_sha256}/"
        f"{candidate_sha256}/"
        f"{_sha256(body)}.json"
    )
    if key != expected_key:
        raise CandidateJournalError(
            f"Terminal candidate resolution {key} does not match its content identity"
        )

    decision_body = s3.get_object(
        Bucket=config.s3_bucket,
        Key=typed_decision_key,
    )["Body"].read()
    if _sha256(decision_body) != decision_sha256:
        raise CandidateJournalError(
            f"Terminal candidate resolution {key} decision digest does not match"
        )
    decision = _decode_decision(
        s3,
        config,
        decision_body,
        key=typed_decision_key,
    )
    candidate_body = s3.get_object(
        Bucket=config.s3_bucket,
        Key=typed_candidate_key,
    )["Body"].read()
    candidate = _decode_candidate(
        candidate_body,
        key=typed_candidate_key,
        expected_prefix=(f"{config.s3_scraper_prefix}/runs/{typed_run_id}/terminal-candidates/v1/"),
    )
    canonical_body = s3.get_object(
        Bucket=config.s3_bucket,
        Key=cast(str, canonical_key),
    )["Body"].read()
    if (
        decision.run_id != typed_run_id
        or decision.item_id != typed_item_id
        or decision.kind != decision_kind
        or decision.candidate.key != decision_candidate_key
        or decision.candidate.candidate_sha256 != decision_candidate_sha256
        or decision.candidate.observation_sha256 != decision_candidate_observation_sha256
        or decision.canonical_key != canonical_key
        or candidate.run_id != typed_run_id
        or candidate.item_id != typed_item_id
        or candidate.kind != candidate_kind
        or candidate.candidate_sha256 != candidate_sha256
        or candidate.observation_sha256 != candidate_observation_sha256
        or _sha256(canonical_body) != canonical_sha256
        or canonical_body != decision.candidate.candidate_body
        or decision.candidate.observation_sha256 != canonical_observation_sha256
        or decision.candidate.result.status.value != canonical_status
    ):
        raise CandidateJournalError(
            f"Terminal candidate resolution {key} does not match retained evidence"
        )
    if candidate.key == decision.candidate.key or (
        candidate.kind == decision.kind
        and semantic_observation(candidate.result)
        == semantic_observation(decision.candidate.result)
    ):
        raise CandidateJournalError(
            f"Terminal candidate resolution {key} does not resolve a disagreement"
        )
    return TerminalCandidateResolution(
        key=key,
        body_sha256=_sha256(body),
        run_id=typed_run_id,
        item_id=typed_item_id,
        decision_key=typed_decision_key,
        decision_sha256=cast(str, decision_sha256),
        decision_kind=cast(TerminalKind, decision_kind),
        decision_candidate_sha256=cast(str, decision_candidate_sha256),
        canonical_key=cast(str, canonical_key),
        canonical_sha256=cast(str, canonical_sha256),
        candidate_key=typed_candidate_key,
        candidate_kind=cast(TerminalKind, candidate_kind),
        candidate_sha256=cast(str, candidate_sha256),
    )


def write_accept_terminal_decision_resolution(
    s3: S3Client,
    config: WorkerConfig,
    *,
    run_id: str,
    decision_key: str,
    candidate_key: str,
    expected_decision_sha256: str,
    expected_candidate_sha256: str,
    expected_canonical_sha256: str,
    reviewed_at: datetime,
    reviewed_by: str,
    review_note: str,
) -> TerminalCandidateResolution:
    """Append an exact human review accepting the terminal decision over a candidate."""
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise ValueError("reviewed_at must include a timezone")
    if not reviewed_by.strip() or not review_note.strip():
        raise ValueError("reviewed_by and review_note must be nonblank")
    if not all(
        _is_sha256(value)
        for value in (
            expected_decision_sha256,
            expected_candidate_sha256,
            expected_canonical_sha256,
        )
    ):
        raise ValueError("expected review digests must be lowercase SHA-256 values")
    decision_body = s3.get_object(Bucket=config.s3_bucket, Key=decision_key)["Body"].read()
    if _sha256(decision_body) != expected_decision_sha256:
        raise ValueError("terminal decision body does not match the reviewed digest")
    decision = _decode_decision(s3, config, decision_body, key=decision_key)
    if decision.run_id != run_id:
        raise ValueError("terminal decision belongs to another run")
    candidate_body = s3.get_object(Bucket=config.s3_bucket, Key=candidate_key)["Body"].read()
    candidate = _decode_candidate(
        candidate_body,
        key=candidate_key,
        expected_prefix=(f"{config.s3_scraper_prefix}/runs/{run_id}/terminal-candidates/v1/"),
    )
    if candidate.candidate_sha256 != expected_candidate_sha256:
        raise ValueError("terminal candidate body does not match the reviewed digest")
    canonical_body = s3.get_object(
        Bucket=config.s3_bucket,
        Key=decision.canonical_key,
    )["Body"].read()
    if _sha256(canonical_body) != expected_canonical_sha256:
        raise ValueError("canonical body does not match the reviewed digest")
    if (
        candidate.run_id != run_id
        or candidate.item_id != decision.item_id
        or canonical_body != decision.candidate.candidate_body
    ):
        raise ValueError("reviewed candidate/decision/canonical identity is invalid")
    if candidate.key == decision.candidate.key or (
        candidate.kind == decision.kind
        and semantic_observation(candidate.result)
        == semantic_observation(decision.candidate.result)
    ):
        raise ValueError("reviewed candidate does not disagree with the terminal decision")
    record = {
        "schema_version": RESOLUTION_SCHEMA_VERSION,
        "policy_version": 1,
        "resolution_type": "accept-decision",
        "reviewed_at": reviewed_at.isoformat(),
        "reviewed_by": reviewed_by.strip(),
        "review_note": review_note.strip(),
        "run_id": run_id,
        "item_id": candidate.item_id,
        "decision_key": decision.key,
        "decision_sha256": decision.body_sha256,
        "decision_kind": decision.kind,
        "decision_candidate_key": decision.candidate.key,
        "decision_candidate_sha256": decision.candidate.candidate_sha256,
        "decision_candidate_observation_sha256": decision.candidate.observation_sha256,
        "canonical_key": decision.canonical_key,
        "canonical_sha256": _sha256(canonical_body),
        "canonical_observation_sha256": decision.candidate.observation_sha256,
        "canonical_status": decision.candidate.result.status.value,
        "rejected_candidate_key": candidate.key,
        "rejected_candidate_kind": candidate.kind,
        "rejected_candidate_sha256": candidate.candidate_sha256,
        "rejected_candidate_observation_sha256": candidate.observation_sha256,
    }
    body = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    prefix = _candidate_resolution_prefix(config, run_id)
    key = (
        f"{prefix}{_sha256(candidate.item_id.encode())}/{decision.body_sha256}/"
        f"{candidate.candidate_sha256}/{_sha256(body)}.json"
    )
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except Exception as exc:
        put_error = exc
    else:
        put_error = None
    try:
        observed = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        resolution = _decode_candidate_resolution(
            s3,
            config,
            observed,
            key=key,
            expected_run_id=run_id,
        )
    except Exception as exc:
        raise CandidateJournalError(
            f"Could not durably commit terminal candidate resolution for "
            f"run={run_id}, item={candidate.item_id}"
        ) from (put_error or exc)
    if observed != body:
        raise CandidateJournalError(
            f"Terminal candidate resolution readback mismatch for "
            f"run={run_id}, item={candidate.item_id}"
        )
    return resolution


def read_terminal_candidate_resolutions(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> tuple[TerminalCandidateResolution, ...]:
    """Read and validate every explicit terminal-candidate review for one run."""
    prefix = _candidate_resolution_prefix(config, run_id)
    paginator = s3.get_paginator("list_objects_v2")
    keys: set[str] = set()
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if isinstance(key, str) and key.startswith(prefix):
                keys.add(key)
    resolutions: list[TerminalCandidateResolution] = []
    for key in sorted(keys):
        if not key.endswith(".json"):
            raise CandidateJournalError(
                f"Unexpected non-JSON terminal candidate resolution object {key}"
            )
        body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        resolutions.append(
            _decode_candidate_resolution(
                s3,
                config,
                body,
                key=key,
                expected_run_id=run_id,
            )
        )
    return tuple(resolutions)


def _delivery_identity(
    delivery_metadata: dict[str, object],
    *,
    label: str,
) -> tuple[str, str, int]:
    delivery = _validate_delivery_metadata(delivery_metadata, label=label)
    message_id = delivery.get("message_id")
    body_sha256 = delivery.get("body_sha256")
    system_attributes = delivery.get("system_attributes")
    receive_count_raw = (
        system_attributes.get("ApproximateReceiveCount")
        if isinstance(system_attributes, dict)
        else None
    )
    if not isinstance(message_id, str) or not message_id:
        raise CandidateJournalError(f"{label} lacks a stable SQS MessageId")
    if not _is_sha256(body_sha256):
        raise CandidateJournalError(f"{label} lacks a valid message body digest")
    if (
        not isinstance(receive_count_raw, str)
        or not receive_count_raw.isdigit()
        or int(receive_count_raw) < 1
    ):
        raise CandidateJournalError(f"{label} lacks a valid receive count")
    return message_id, body_sha256, int(receive_count_raw)


def _disposition_prefix(
    config: WorkerConfig,
    run_id: str,
    item_id: str,
    message_id: str,
) -> str:
    return (
        f"{config.s3_scraper_prefix}/runs/{run_id}/terminal-dispositions/v1/"
        f"{_sha256(item_id.encode())}/{_sha256(message_id.encode())}/"
    )


def _decode_disposition(
    body: bytes,
    *,
    key: str,
    expected_prefix: str,
) -> TerminalDisposition:
    try:
        record = decode_strict_json_object(body, label=f"Terminal disposition {key}")
    except ValueError as exc:
        raise CandidateJournalError(str(exc)) from exc
    if set(record) != _DISPOSITION_FIELDS:
        raise CandidateJournalError(
            f"Terminal disposition {key} fields are incomplete or unexpected"
        )
    schema_version = record.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != DISPOSITION_SCHEMA_VERSION
    ):
        raise CandidateJournalError(f"Terminal disposition {key} has an unsupported schema")
    _validate_timestamp(record.get("recorded_at"), label=f"Terminal disposition {key}")

    run_id = record.get("run_id")
    item_id = record.get("item_id")
    message_id = record.get("message_id")
    message_body_sha256 = record.get("message_body_sha256")
    receive_count = record.get("receive_count")
    kind = record.get("kind")
    outcome = record.get("outcome")
    candidate_key = record.get("candidate_key")
    candidate_sha256 = record.get("candidate_sha256")
    candidate_observation_sha256 = record.get("candidate_observation_sha256")
    canonical_key = record.get("canonical_key")
    canonical_sha256 = record.get("canonical_sha256")
    canonical_observation_sha256 = record.get("canonical_observation_sha256")
    conflict_evidence_key = record.get("conflict_evidence_key")
    for label, value in (
        ("run ID", run_id),
        ("item ID", item_id),
        ("message ID", message_id),
        ("candidate key", candidate_key),
        ("canonical key", canonical_key),
    ):
        if not isinstance(value, str) or not value:
            raise CandidateJournalError(f"Terminal disposition {key} has an invalid {label}")
    if not _is_sha256(message_body_sha256):
        raise CandidateJournalError(
            f"Terminal disposition {key} has an invalid message body digest"
        )
    if not isinstance(receive_count, int) or isinstance(receive_count, bool) or receive_count < 1:
        raise CandidateJournalError(f"Terminal disposition {key} has an invalid receive count")
    if kind not in {"result", "failure"}:
        raise CandidateJournalError(f"Terminal disposition {key} has an invalid kind")
    if outcome not in {"created", "duplicate", "conflict"}:
        raise CandidateJournalError(f"Terminal disposition {key} has an invalid outcome")
    for label, value in (
        ("candidate digest", candidate_sha256),
        ("candidate observation digest", candidate_observation_sha256),
        ("canonical digest", canonical_sha256),
    ):
        if not _is_sha256(value):
            raise CandidateJournalError(f"Terminal disposition {key} has an invalid {label}")
    if canonical_observation_sha256 is not None and not _is_sha256(canonical_observation_sha256):
        raise CandidateJournalError(
            f"Terminal disposition {key} has an invalid canonical observation digest"
        )
    if conflict_evidence_key is not None and (
        not isinstance(conflict_evidence_key, str) or not conflict_evidence_key
    ):
        raise CandidateJournalError(
            f"Terminal disposition {key} has an invalid conflict evidence key"
        )

    typed_kind = cast(TerminalKind, kind)
    typed_outcome = cast(DispositionOutcome, outcome)
    expected_key = f"{expected_prefix}{candidate_sha256}-{typed_outcome}.json"
    if key != expected_key:
        raise CandidateJournalError(f"Terminal disposition {key} does not match its key identity")
    if typed_outcome == "conflict":
        if conflict_evidence_key is None:
            raise CandidateJournalError(f"Terminal disposition {key} lacks conflict evidence")
    elif conflict_evidence_key is not None:
        raise CandidateJournalError(f"Terminal disposition {key} has unexpected conflict evidence")
    return TerminalDisposition(
        key=key,
        run_id=cast(str, run_id),
        item_id=cast(str, item_id),
        message_id=cast(str, message_id),
        message_body_sha256=message_body_sha256,
        receive_count=receive_count,
        kind=typed_kind,
        outcome=typed_outcome,
        candidate_key=cast(str, candidate_key),
        candidate_sha256=cast(str, candidate_sha256),
        candidate_observation_sha256=cast(str, candidate_observation_sha256),
        canonical_key=cast(str, canonical_key),
        canonical_sha256=cast(str, canonical_sha256),
        canonical_observation_sha256=canonical_observation_sha256,
        conflict_evidence_key=cast(str | None, conflict_evidence_key),
    )


def write_terminal_candidate(
    s3: S3Client,
    config: WorkerConfig,
    *,
    run_id: str,
    item_id: str,
    kind: TerminalKind,
    candidate_body: bytes,
    result: ScrapeResult,
    delivery_metadata: dict[str, object] | None = None,
) -> TerminalCandidate:
    """Commit one candidate before any first-writer canonical CAS."""
    _validate_candidate_result(result, run_id=run_id, item_id=item_id, kind=kind)
    candidate_sha256 = _sha256(candidate_body)
    observation_sha256 = _sha256(_observation_body(result))
    key = _candidate_key(config, run_id, item_id, kind, candidate_sha256)
    safe_delivery = _validate_delivery_metadata(
        delivery_metadata or {},
        label="Terminal candidate",
    )
    record = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "recorded_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "item_id": item_id,
        "kind": kind,
        "candidate_sha256": candidate_sha256,
        "observation_sha256": observation_sha256,
        "candidate_body_base64": base64.b64encode(candidate_body).decode("ascii"),
        "sqs_delivery": safe_delivery,
    }
    record_body = json.dumps(record, sort_keys=True, allow_nan=False).encode()
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=key,
            Body=record_body,
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except Exception as exc:
        try:
            observed = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
            candidate = _decode_candidate(
                observed,
                key=key,
                expected_prefix=(
                    f"{config.s3_scraper_prefix}/runs/{run_id}/terminal-candidates/v1/"
                ),
            )
        except Exception:
            raise CandidateJournalError(
                f"Could not durably commit terminal candidate for run={run_id}, item={item_id}"
            ) from exc
        if candidate.candidate_body != candidate_body:
            raise CandidateJournalError(
                f"Terminal candidate key collision for run={run_id}, item={item_id}"
            ) from exc
        return candidate
    return _decode_candidate(
        record_body,
        key=key,
        expected_prefix=f"{config.s3_scraper_prefix}/runs/{run_id}/terminal-candidates/v1/",
    )


def write_terminal_disposition(
    s3: S3Client,
    config: WorkerConfig,
    *,
    run_id: str,
    item_id: str,
    delivery_metadata: dict[str, object],
    candidate: TerminalCandidate,
    canonical_key: str,
    canonical_body: bytes,
    canonical_result: ScrapeResult | None,
    outcome: DispositionOutcome,
    conflict_evidence_key: str | None = None,
) -> TerminalDisposition:
    """Commit a message-bound terminal outcome before deleting its SQS copy."""
    message_id, message_body_sha256, receive_count = _delivery_identity(
        delivery_metadata,
        label="Terminal disposition",
    )
    if candidate.run_id != run_id or candidate.item_id != item_id:
        raise CandidateJournalError("Terminal disposition candidate identity is invalid")
    canonical_sha256 = _sha256(canonical_body)
    canonical_observation_sha256 = (
        _sha256(_observation_body(canonical_result)) if canonical_result is not None else None
    )
    if outcome in {"created", "duplicate"}:
        if (
            canonical_result is None
            or canonical_result.run_id != run_id
            or canonical_result.item_id != item_id
            or candidate.kind
            != (
                "result"
                if canonical_result.status in {ScrapeStatus.SUCCESS, ScrapeStatus.NO_RESULTS}
                else "failure"
            )
            or candidate.observation_sha256 != canonical_observation_sha256
        ):
            raise CandidateJournalError(
                "Terminal disposition cannot reuse a semantically different canonical"
            )
        if conflict_evidence_key is not None:
            raise CandidateJournalError("Non-conflict terminal disposition has conflict evidence")
    elif not conflict_evidence_key:
        raise CandidateJournalError("Conflict terminal disposition lacks conflict evidence")

    prefix = _disposition_prefix(config, run_id, item_id, message_id)
    key = f"{prefix}{candidate.candidate_sha256}-{outcome}.json"
    record = {
        "schema_version": DISPOSITION_SCHEMA_VERSION,
        "recorded_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "item_id": item_id,
        "message_id": message_id,
        "message_body_sha256": message_body_sha256,
        "receive_count": receive_count,
        "kind": candidate.kind,
        "outcome": outcome,
        "candidate_key": candidate.key,
        "candidate_sha256": candidate.candidate_sha256,
        "candidate_observation_sha256": candidate.observation_sha256,
        "canonical_key": canonical_key,
        "canonical_sha256": canonical_sha256,
        "canonical_observation_sha256": canonical_observation_sha256,
        "conflict_evidence_key": conflict_evidence_key,
    }
    body = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except Exception as exc:
        try:
            observed = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
            disposition = _decode_disposition(
                observed,
                key=key,
                expected_prefix=prefix,
            )
        except Exception:
            raise CandidateJournalError(
                f"Could not durably commit terminal disposition for run={run_id}, "
                f"item={item_id}, message={message_id}"
            ) from exc
        expected_bindings = (
            run_id,
            item_id,
            message_id,
            message_body_sha256,
            candidate.key,
            candidate.candidate_sha256,
            candidate.observation_sha256,
            canonical_key,
            canonical_sha256,
            canonical_observation_sha256,
            outcome,
            conflict_evidence_key,
        )
        observed_bindings = (
            disposition.run_id,
            disposition.item_id,
            disposition.message_id,
            disposition.message_body_sha256,
            disposition.candidate_key,
            disposition.candidate_sha256,
            disposition.candidate_observation_sha256,
            disposition.canonical_key,
            disposition.canonical_sha256,
            disposition.canonical_observation_sha256,
            disposition.outcome,
            disposition.conflict_evidence_key,
        )
        if observed_bindings != expected_bindings:
            raise CandidateJournalError(
                f"Terminal disposition key collision for run={run_id}, item={item_id}"
            ) from exc
        return disposition
    try:
        observed = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        disposition = _decode_disposition(
            observed,
            key=key,
            expected_prefix=prefix,
        )
    except Exception as exc:
        raise CandidateJournalError(
            f"Could not verify terminal disposition for run={run_id}, item={item_id}, "
            f"message={message_id}"
        ) from exc
    if observed != body:
        raise CandidateJournalError(
            f"Terminal disposition readback mismatch for run={run_id}, item={item_id}"
        )
    return disposition


def read_terminal_candidates(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> tuple[TerminalCandidate, ...]:
    """Read and validate every content-addressed candidate for one run."""
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/terminal-candidates/v1/"
    paginator = s3.get_paginator("list_objects_v2")
    keys: set[str] = set()
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if isinstance(key, str) and key.startswith(prefix):
                keys.add(key)
    candidates: list[TerminalCandidate] = []
    for key in sorted(keys):
        if not key.endswith(".json"):
            raise CandidateJournalError(f"Unexpected non-JSON terminal candidate object {key}")
        body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        candidate = _decode_candidate(body, key=key, expected_prefix=prefix)
        if candidate.run_id != run_id:
            raise CandidateJournalError(f"Terminal candidate {key} belongs to another run")
        candidates.append(candidate)
    return tuple(candidates)


__all__ = [
    "CandidateJournalError",
    "DECISION_SCHEMA_VERSION",
    "DISPOSITION_SCHEMA_VERSION",
    "JOURNAL_SCHEMA_VERSION",
    "RESOLUTION_SCHEMA_VERSION",
    "TERMINAL_DECISION_RESOLUTION_PATH",
    "TerminalCandidate",
    "TerminalCandidateResolution",
    "TerminalDecision",
    "TerminalDecisionConflict",
    "TerminalDisposition",
    "claim_terminal_decision",
    "read_terminal_candidates",
    "read_terminal_candidate_resolutions",
    "read_terminal_decision_conflicts",
    "read_terminal_decisions",
    "write_accept_terminal_decision_resolution",
    "write_terminal_candidate",
    "write_terminal_decision_conflict",
    "write_terminal_disposition",
]
