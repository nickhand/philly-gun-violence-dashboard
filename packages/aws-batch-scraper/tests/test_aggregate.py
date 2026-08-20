"""Contracts for exact-run manifest and input aggregation."""

import base64
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from aws_batch_scraper.aggregate import (
    ResultConflictReport,
    RunManifest,
    RunResultConflictError,
    aggregate_results,
    audit_result_conflicts,
    read_run_items,
    read_run_manifest,
    require_no_result_conflicts,
    write_accept_canonical_resolution,
)
from aws_batch_scraper.config import WorkerConfig
from aws_batch_scraper.result_semantics import (
    SEMANTIC_OBSERVATION_FIELDS,
    semantic_observation,
)
from aws_batch_scraper.types import ScrapeResult, ScrapeStatus, WorkItem
from botocore.exceptions import ClientError
from pydantic import ValidationError


def _config() -> WorkerConfig:
    return WorkerConfig(
        _env_file=None,
        s3_bucket="bucket",
        s3_scraper_prefix="scraper",
        aws_account_id="123456789012",
        sqs_queue_name="queue",
        sqs_dlq_name="queue-dlq",
    )


def _s3_with_run(*, manifest: object, input_body: bytes) -> MagicMock:
    objects = {
        "scraper/runs/run-1/manifest.json": json.dumps(manifest).encode(),
        "scraper/runs/run-1/input.jsonl": input_body,
    }
    s3 = MagicMock()
    s3.get_object.side_effect = lambda *, Bucket, Key: {"Body": BytesIO(objects[Key])}
    return s3


def _manifest(**overrides: object) -> dict[str, object]:
    return {
        "run_id": "run-1",
        "selection_mode": "full",
        "candidate_count": 1,
        "input_size": 1,
        "completed_at": "2026-08-18T12:00:00+00:00",
        **overrides,
    }


def test_completed_run_items_require_exact_manifest_identity_and_count() -> None:
    s3 = _s3_with_run(
        manifest=_manifest(),
        input_body=b'{"item_id":"100","source":"test"}',
    )

    items = read_run_items(s3, _config(), "run-1", require_completed=True)

    assert items == [WorkItem(item_id="100", extra={"source": "test"})]


def test_manifest_reader_exposes_immutable_selection_provenance() -> None:
    s3 = _s3_with_run(
        manifest=_manifest(selection_mode="sample", candidate_count=10),
        input_body=b'{"item_id":"100"}',
    )

    manifest = read_run_manifest(s3, _config(), "run-1", require_completed=True)

    assert manifest == RunManifest(
        run_id="run-1",
        selection_mode="sample",
        candidate_count=10,
        input_size=1,
        completed_at="2026-08-18T12:00:00+00:00",
    )


def test_incomplete_run_cannot_be_processed_while_workers_may_be_live() -> None:
    s3 = _s3_with_run(
        manifest=_manifest(completed_at=None),
        input_body=b'{"item_id":"100"}',
    )

    with pytest.raises(ValueError, match="has not been completed"):
        read_run_items(s3, _config(), "run-1", require_completed=True)


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        (_manifest(run_id="run-other"), "identity"),
        (
            _manifest(selection_mode="sample", candidate_count=2, input_size=2),
            "declares 2",
        ),
        (_manifest(completed_at="2026-08-18T12:00:00"), "manifest.*invalid"),
        (
            _manifest(selection_mode="full", candidate_count=2),
            "manifest.*invalid",
        ),
        (
            _manifest(selection_mode="sample", candidate_count=0),
            "manifest.*invalid",
        ),
        (
            _manifest(selection_mode="preview"),
            "manifest.*invalid",
        ),
        (
            {key: value for key, value in _manifest().items() if key != "selection_mode"},
            "manifest.*invalid",
        ),
    ],
)
def test_run_manifest_mismatch_fails_closed(
    manifest: object,
    message: str,
) -> None:
    s3 = _s3_with_run(manifest=manifest, input_body=b'{"item_id":"100"}')

    with pytest.raises(ValueError, match=message):
        read_run_items(s3, _config(), "run-1", require_completed=True)


def test_run_input_rejects_nonstandard_json_numbers() -> None:
    s3 = _s3_with_run(
        manifest=_manifest(),
        input_body=b'{"item_id":"100","score":NaN}',
    )

    with pytest.raises(ValueError, match="invalid JSON"):
        read_run_items(s3, _config(), "run-1", require_completed=True)


def _s3_with_results(objects: Mapping[str, bytes | Exception]) -> MagicMock:
    stored = dict(objects)

    class Paginator:
        def paginate(self, **kwargs):
            prefix = kwargs["Prefix"]
            return [
                {
                    "Contents": [{"Key": key} for key in stored if key.startswith(prefix)],
                }
            ]

    s3 = MagicMock()
    s3.get_paginator.return_value = Paginator()

    def get_object(*, Bucket: str, Key: str) -> dict[str, BytesIO]:
        value = stored[Key]
        if isinstance(value, Exception):
            raise value
        return {"Body": BytesIO(value)}

    s3.get_object.side_effect = get_object

    def put_object(**kwargs):
        key = kwargs["Key"]
        if kwargs.get("IfNoneMatch") == "*" and key in stored:
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "exists"}},
                "PutObject",
            )
        stored[key] = kwargs["Body"]
        return {"ETag": '"etag"'}

    s3.put_object.side_effect = put_object
    s3.objects = stored
    return s3


def _result(*, item_id: str = "100", run_id: str = "run-1") -> bytes:
    result = ScrapeResult(
        status=ScrapeStatus.NO_RESULTS,
        item_id=item_id,
        run_id=run_id,
    )
    return result.model_dump_json().encode()


def _legacy_extra_only_conflict(
    canonical_body: bytes,
    *,
    item_id: str = "100",
    run_id: str = "run-1",
    status: str = "NO_RESULTS",
) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "terminal_status": "result-conflict",
            "run_id": run_id,
            "item_id": item_id,
            "reason": "exact-run observations disagree",
            "existing_sha256": hashlib.sha256(canonical_body).hexdigest(),
            "candidate_sha256": "f" * 64,
            "existing_status": status,
            "candidate_status": status,
            "differing_fields": ["extra"],
        },
        sort_keys=True,
    ).encode()


def _v2_conflict(canonical_body: bytes) -> tuple[str, bytes]:
    canonical = ScrapeResult.model_validate_json(canonical_body)
    candidate = ScrapeResult(
        status=ScrapeStatus.SUCCESS,
        data={"results": [{"case": "1"}]},
        classification="found",
        item_id="100",
        run_id="run-1",
    )
    candidate_body = candidate.model_dump_json().encode()
    candidate_sha256 = hashlib.sha256(candidate_body).hexdigest()
    canonical_observation = semantic_observation(canonical)
    candidate_observation = semantic_observation(candidate)
    record = {
        "schema_version": 2,
        "terminal_status": "result-conflict",
        "run_id": "run-1",
        "item_id": "100",
        "reason": "exact-run observations disagree",
        "existing_sha256": hashlib.sha256(canonical_body).hexdigest(),
        "candidate_sha256": candidate_sha256,
        "existing_status": canonical.status.value,
        "candidate_status": candidate.status.value,
        "differing_fields": sorted(
            field
            for field in SEMANTIC_OBSERVATION_FIELDS
            if canonical_observation.get(field) != candidate_observation.get(field)
        ),
        "canonical_result_key": "scraper/runs/run-1/results/100.json",
        "existing_evidence": {
            "body_sha256": hashlib.sha256(canonical_body).hexdigest(),
            "semantic_observation": canonical_observation,
            "result": canonical.model_dump(mode="json"),
        },
        "candidate_evidence": {
            "body_sha256": candidate_sha256,
            "body_base64": base64.b64encode(candidate_body).decode(),
            "semantic_observation": candidate_observation,
            "result": candidate.model_dump(mode="json"),
        },
        "sqs_delivery": {},
    }
    key = f"scraper/runs/run-1/result-conflicts/v2/100/{candidate_sha256}.json"
    return key, json.dumps(record, sort_keys=True).encode()


def test_exact_run_aggregation_rejects_mismatched_item_identity() -> None:
    s3 = _s3_with_results({"scraper/runs/run-1/results/100.json": _result(item_id="wrong-item")})

    with pytest.raises(ValueError, match="contains item identity"):
        aggregate_results(s3, _config(), run_id="run-1")


def test_exact_run_aggregation_rejects_mismatched_run_identity() -> None:
    s3 = _s3_with_results({"scraper/runs/run-1/results/100.json": _result(run_id="run-other")})

    with pytest.raises(ValueError, match="belongs to run"):
        aggregate_results(s3, _config(), run_id="run-1")


def test_exact_run_aggregation_fails_closed_on_s3_read_error() -> None:
    s3 = _s3_with_results(
        {
            "scraper/runs/run-1/results/100.json": _result(),
            "scraper/runs/run-1/results/200.json": PermissionError("access denied"),
        }
    )

    with pytest.raises(PermissionError, match="access denied"):
        aggregate_results(s3, _config(), run_id="run-1")


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b'{"status":"NO_RESULTS","item_id":100,"run_id":"run-1"}',
        b'{"status":"NO_RESULTS","status":"SUCCESS","item_id":"100","run_id":"run-1"}',
        b'{"status":"NO_RESULTS","data":{"results":[],"results":[1]},"item_id":"100","run_id":"run-1"}',
    ],
)
def test_exact_run_aggregation_fails_closed_on_invalid_result(body: bytes) -> None:
    s3 = _s3_with_results({"scraper/runs/run-1/results/100.json": body})

    with pytest.raises((ValidationError, ValueError)):
        aggregate_results(s3, _config(), run_id="run-1")


def test_result_conflict_evidence_blocks_exact_run_publication() -> None:
    conflict_key = "scraper/runs/run-1/result-conflicts/100.json"
    s3 = _s3_with_results({conflict_key: b'{"terminal_status":"result-conflict"}'})

    with pytest.raises(RunResultConflictError, match="Refusing to aggregate or publish"):
        require_no_result_conflicts(s3, _config(), "run-1")


def test_empty_conflict_report_has_stable_digest() -> None:
    s3 = _s3_with_results({"scraper/runs/run-1/results/100.json": _result()})

    report = require_no_result_conflicts(s3, _config(), "run-1")

    assert report == ResultConflictReport.empty()
    assert report.conflict_policy_version == 1
    assert len(report.evidence_sha256) == 64


def _write_exact_review(
    s3: MagicMock,
    *,
    conflict_key: str,
    conflict_body: bytes,
) -> str:
    conflict = json.loads(conflict_body)
    return write_accept_canonical_resolution(
        s3,
        _config(),
        run_id="run-1",
        conflict_key=conflict_key,
        expected_conflict_sha256=hashlib.sha256(conflict_body).hexdigest(),
        expected_existing_sha256=conflict["existing_sha256"],
        expected_candidate_sha256=conflict["candidate_sha256"],
        expected_candidate_status=ScrapeStatus(conflict["candidate_status"]),
        expected_differing_fields=tuple(conflict["differing_fields"]),
        expected_canonical_sha256=conflict["existing_sha256"],
        expected_canonical_status=ScrapeStatus(conflict["existing_status"]),
        reviewed_at=datetime(2026, 8, 20, 20, 0, tzinfo=UTC),
        reviewed_by="operator@example.test",
        review_note="Reviewed both observations; accept the immutable canonical result.",
    )


def test_legacy_extra_only_conflict_blocks_without_explicit_review() -> None:
    result_key = "scraper/runs/run-1/results/100.json"
    conflict_key = "scraper/runs/run-1/result-conflicts/100.json"
    canonical_body = _result()
    conflict_body = _legacy_extra_only_conflict(canonical_body)
    s3 = _s3_with_results(
        {
            result_key: canonical_body,
            conflict_key: conflict_body,
        }
    )

    report = audit_result_conflicts(s3, _config(), "run-1")

    assert report == ResultConflictReport(
        conflict_policy_version=1,
        total_count=1,
        resolved_count=0,
        unresolved_count=1,
        evidence_sha256=report.evidence_sha256,
        resolved_keys=(),
        unresolved_keys=(conflict_key,),
    )
    with pytest.raises(RunResultConflictError, match="unresolved durable result conflict"):
        require_no_result_conflicts(s3, _config(), "run-1")
    assert s3.put_object.call_count == 0


def test_exact_append_only_review_resolves_without_mutating_conflict() -> None:
    result_key = "scraper/runs/run-1/results/100.json"
    conflict_key = "scraper/runs/run-1/result-conflicts/100.json"
    canonical_body = _result()
    conflict_body = _legacy_extra_only_conflict(canonical_body)
    s3 = _s3_with_results({result_key: canonical_body, conflict_key: conflict_body})

    resolution_key = _write_exact_review(
        s3,
        conflict_key=conflict_key,
        conflict_body=conflict_body,
    )
    repeated_key = _write_exact_review(
        s3,
        conflict_key=conflict_key,
        conflict_body=conflict_body,
    )
    report = require_no_result_conflicts(s3, _config(), "run-1")

    assert repeated_key == resolution_key
    assert "/result-conflict-resolutions/v1/" in resolution_key
    assert report.total_count == report.resolved_count == 1
    assert report.unresolved_count == 0
    assert report.resolved_keys == (conflict_key,)
    assert aggregate_results(s3, _config(), run_id="run-1")["100"].status == (
        ScrapeStatus.NO_RESULTS
    )
    assert s3.get_object(Bucket="bucket", Key=conflict_key)["Body"].read() == conflict_body


def test_exact_review_can_resolve_cryptographically_valid_v2_evidence() -> None:
    result_key = "scraper/runs/run-1/results/100.json"
    canonical_body = _result()
    conflict_key, conflict_body = _v2_conflict(canonical_body)
    s3 = _s3_with_results({result_key: canonical_body, conflict_key: conflict_body})

    _write_exact_review(s3, conflict_key=conflict_key, conflict_body=conflict_body)

    report = require_no_result_conflicts(s3, _config(), "run-1")
    assert report.resolved_count == 1
    assert report.unresolved_count == 0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda record: record.pop("candidate_evidence"),
        lambda record: record["candidate_evidence"].update(
            body_base64=base64.b64encode(b"forged").decode()
        ),
        lambda record: record["candidate_evidence"].update(semantic_observation={}),
        lambda record: record.update(differing_fields=[]),
        lambda record: record.update(canonical_result_key="wrong/key.json"),
        lambda record: record.update(candidate_status="NO_RESULTS"),
    ],
)
def test_resolution_rejects_missing_or_forged_v2_candidate_evidence(mutation) -> None:
    result_key = "scraper/runs/run-1/results/100.json"
    canonical_body = _result()
    conflict_key, conflict_body = _v2_conflict(canonical_body)
    record = json.loads(conflict_body)
    mutation(record)
    mutated_body = json.dumps(record, sort_keys=True).encode()
    s3 = _s3_with_results({result_key: canonical_body, conflict_key: mutated_body})

    with pytest.raises(ValueError):
        _write_exact_review(
            s3,
            conflict_key=conflict_key,
            conflict_body=mutated_body,
        )
    assert audit_result_conflicts(s3, _config(), "run-1").unresolved_count == 1


def test_conflict_report_digest_and_key_order_are_deterministic() -> None:
    first_body = _result(item_id="100")
    second_body = _result(item_id="200")
    objects = {
        "scraper/runs/run-1/result-conflicts/200.json": _legacy_extra_only_conflict(
            second_body,
            item_id="200",
        ),
        "scraper/runs/run-1/results/200.json": second_body,
        "scraper/runs/run-1/result-conflicts/100.json": _legacy_extra_only_conflict(first_body),
        "scraper/runs/run-1/results/100.json": first_body,
    }
    reverse_objects = dict(reversed(list(objects.items())))

    first = audit_result_conflicts(_s3_with_results(objects), _config(), "run-1")
    second = audit_result_conflicts(
        _s3_with_results(reverse_objects),
        _config(),
        "run-1",
    )

    assert first == second
    assert first.unresolved_keys == (
        "scraper/runs/run-1/result-conflicts/100.json",
        "scraper/runs/run-1/result-conflicts/200.json",
    )


@pytest.mark.parametrize(
    "expected_override",
    [
        {"expected_conflict_sha256": "0" * 64},
        {"expected_existing_sha256": "0" * 64},
        {"expected_candidate_sha256": "0" * 64},
        {"expected_candidate_status": ScrapeStatus.SUCCESS},
        {"expected_differing_fields": ("status",)},
        {"expected_canonical_sha256": "0" * 64},
        {"expected_canonical_status": ScrapeStatus.SUCCESS},
    ],
)
def test_resolution_writer_rejects_wrong_reviewed_binding(
    expected_override: dict[str, object],
) -> None:
    result_key = "scraper/runs/run-1/results/100.json"
    conflict_key = "scraper/runs/run-1/result-conflicts/100.json"
    canonical_body = _result()
    conflict_body = _legacy_extra_only_conflict(canonical_body)
    conflict = json.loads(conflict_body)
    s3 = _s3_with_results({result_key: canonical_body, conflict_key: conflict_body})
    arguments: dict[str, object] = {
        "run_id": "run-1",
        "conflict_key": conflict_key,
        "expected_conflict_sha256": hashlib.sha256(conflict_body).hexdigest(),
        "expected_existing_sha256": conflict["existing_sha256"],
        "expected_candidate_sha256": conflict["candidate_sha256"],
        "expected_candidate_status": ScrapeStatus.NO_RESULTS,
        "expected_differing_fields": ("extra",),
        "expected_canonical_sha256": conflict["existing_sha256"],
        "expected_canonical_status": ScrapeStatus.NO_RESULTS,
        "reviewed_at": datetime(2026, 8, 20, 20, 0, tzinfo=UTC),
        "reviewed_by": "operator@example.test",
        "review_note": "reviewed",
        **expected_override,
    }

    with pytest.raises(ValueError):
        write_accept_canonical_resolution(s3, _config(), **arguments)  # ty: ignore[invalid-argument-type]
    assert s3.put_object.call_count == 0


@pytest.mark.parametrize(
    "canonical_body",
    [
        b"not-json",
        _result(item_id="other"),
        _result(run_id="run-other"),
        ScrapeResult(
            status=ScrapeStatus.SUCCESS,
            data={"results": [{"case": "1"}]},
            item_id="100",
            run_id="run-1",
        )
        .model_dump_json()
        .encode(),
    ],
)
def test_resolution_writer_rejects_invalid_canonical_binding(
    canonical_body: bytes,
) -> None:
    result_key = "scraper/runs/run-1/results/100.json"
    conflict_key = "scraper/runs/run-1/result-conflicts/100.json"
    s3 = _s3_with_results(
        {
            result_key: canonical_body,
            conflict_key: _legacy_extra_only_conflict(canonical_body),
        }
    )

    with pytest.raises((ValueError, KeyError)):
        _write_exact_review(
            s3,
            conflict_key=conflict_key,
            conflict_body=_legacy_extra_only_conflict(canonical_body),
        )


def test_tampered_resolution_and_unreviewed_v2_conflict_stay_unresolved() -> None:
    result_key = "scraper/runs/run-1/results/100.json"
    legacy_key = "scraper/runs/run-1/result-conflicts/100.json"
    v2_key = "scraper/runs/run-1/result-conflicts/v2/100/" + "a" * 64 + ".json"
    canonical_body = _result()
    legacy_body = _legacy_extra_only_conflict(canonical_body)
    s3 = _s3_with_results(
        {
            result_key: canonical_body,
            legacy_key: legacy_body,
            v2_key: json.dumps(
                {
                    "schema_version": 2,
                    "terminal_status": "result-conflict",
                    "run_id": "run-1",
                    "item_id": "100",
                }
            ).encode(),
        }
    )
    resolution_key = _write_exact_review(
        s3,
        conflict_key=legacy_key,
        conflict_body=legacy_body,
    )
    resolution = json.loads(s3.objects[resolution_key])
    resolution["review_note"] = "tampered"
    s3.objects[resolution_key] = json.dumps(resolution, sort_keys=True).encode()

    report = audit_result_conflicts(s3, _config(), "run-1")

    assert report.total_count == 2
    assert report.resolved_count == 0
    assert report.unresolved_count == 2
    assert report.unresolved_keys == (legacy_key, v2_key)
    with pytest.raises(RunResultConflictError):
        require_no_result_conflicts(s3, _config(), "run-1")


def test_orphan_resolution_object_blocks_even_without_a_conflict() -> None:
    orphan_key = (
        "scraper/runs/run-1/result-conflict-resolutions/v1/" + "a" * 64 + "/" + "b" * 64 + ".json"
    )
    s3 = _s3_with_results({orphan_key: b'{"schema_version":1}'})

    report = audit_result_conflicts(s3, _config(), "run-1")

    assert report.total_count == 0
    assert report.invalid_resolution_count == 1
    assert report.invalid_resolution_keys == (orphan_key,)
    with pytest.raises(RunResultConflictError, match="invalid/orphan resolution"):
        require_no_result_conflicts(s3, _config(), "run-1")


def test_resolution_writer_rejects_corrupt_success_readback() -> None:
    result_key = "scraper/runs/run-1/results/100.json"
    conflict_key = "scraper/runs/run-1/result-conflicts/100.json"
    canonical_body = _result()
    conflict_body = _legacy_extra_only_conflict(canonical_body)
    s3 = _s3_with_results({result_key: canonical_body, conflict_key: conflict_body})
    ordinary_get = s3.get_object.side_effect

    def corrupt_resolution_readback(*, Bucket: str, Key: str):
        if "/result-conflict-resolutions/" in Key and Key in s3.objects:
            return {"Body": BytesIO(b"tampered")}
        return ordinary_get(Bucket=Bucket, Key=Key)

    s3.get_object.side_effect = corrupt_resolution_readback

    with pytest.raises(ValueError, match="readback verification"):
        _write_exact_review(
            s3,
            conflict_key=conflict_key,
            conflict_body=conflict_body,
        )


def test_exact_run_aggregation_always_checks_for_conflict_evidence() -> None:
    conflict_key = "scraper/runs/run-1/result-conflicts/100.json"
    s3 = _s3_with_results(
        {
            "scraper/runs/run-1/results/100.json": _result(),
            conflict_key: b'{"terminal_status":"result-conflict"}',
        }
    )

    with pytest.raises(RunResultConflictError, match="Refusing to aggregate or publish"):
        aggregate_results(s3, _config(), run_id="run-1")
