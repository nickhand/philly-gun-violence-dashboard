"""Contracts for append-only exact-run terminal candidate evidence."""

import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO

import pytest
from aws_batch_scraper.config import WorkerConfig
from aws_batch_scraper.terminal_journal import (
    CandidateJournalError,
    claim_terminal_decision,
    read_terminal_candidate_resolutions,
    read_terminal_candidates,
    write_accept_terminal_decision_resolution,
    write_terminal_candidate,
    write_terminal_disposition,
)
from aws_batch_scraper.types import ScrapeResult, ScrapeStatus
from botocore.exceptions import ClientError


def _config() -> WorkerConfig:
    return WorkerConfig(
        _env_file=None,
        s3_bucket="bucket",
        s3_scraper_prefix="scraper",
        aws_account_id="123456789012",
        sqs_queue_name="queue",
        sqs_dlq_name="queue-dlq",
    )


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "PutObject")


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs):
        key = kwargs["Key"]
        if kwargs.get("IfNoneMatch") == "*" and key in self.objects:
            raise _client_error("PreconditionFailed")
        self.objects[key] = kwargs["Body"]
        return {"ETag": '"etag"'}

    def get_object(self, *, Bucket, Key):
        return {"Body": BytesIO(self.objects[Key]), "ETag": '"etag"'}

    def get_paginator(self, operation: str):
        assert operation == "list_objects_v2"
        owner = self

        class Paginator:
            def paginate(self, *, Bucket, Prefix):
                return [
                    {
                        "Contents": [
                            {"Key": key} for key in sorted(owner.objects) if key.startswith(Prefix)
                        ]
                    }
                ]

        return Paginator()


def _result() -> ScrapeResult:
    return ScrapeResult(
        status=ScrapeStatus.SUCCESS,
        item_id="100/unsafe-path",
        run_id="run-1",
        scraped_at=datetime(2026, 8, 20, tzinfo=UTC),
        data={"cases": ["A"]},
    )


def _failure() -> ScrapeResult:
    return ScrapeResult(
        status=ScrapeStatus.FAILED,
        item_id="100/unsafe-path",
        run_id="run-1",
        scraped_at=datetime(2026, 8, 20, tzinfo=UTC),
        classification="portal-rejected",
    )


def _failure_body(result: ScrapeResult) -> bytes:
    record = result.model_dump(mode="json")
    record["failed_at"] = datetime(2026, 8, 20, 1, tzinfo=UTC).isoformat()
    return json.dumps(record, sort_keys=True).encode()


def test_candidate_round_trip_uses_hashed_item_key_and_safe_delivery_metadata() -> None:
    s3 = FakeS3()
    result = _result()
    body = result.model_dump_json().encode()

    candidate = write_terminal_candidate(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        run_id="run-1",
        item_id="100/unsafe-path",
        kind="result",
        candidate_body=body,
        result=result,
        delivery_metadata={
            "message_id": "message-1",
            "body_sha256": "a" * 64,
            "system_attributes": {"ApproximateReceiveCount": "2"},
        },
    )

    assert "100/unsafe-path" not in candidate.key
    assert read_terminal_candidates(s3, _config(), "run-1") == (candidate,)  # ty: ignore[invalid-argument-type]
    record = json.loads(s3.objects[candidate.key])
    assert "ReceiptHandle" not in json.dumps(record)


def test_candidate_audit_rejects_nested_unknown_delivery_attribute() -> None:
    s3 = FakeS3()
    result = _result()
    candidate = write_terminal_candidate(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        run_id="run-1",
        item_id="100/unsafe-path",
        kind="result",
        candidate_body=result.model_dump_json().encode(),
        result=result,
    )
    record = json.loads(s3.objects[candidate.key])
    record["sqs_delivery"] = {"system_attributes": {"ReceiptHandle": "secret-capability"}}
    s3.objects[candidate.key] = json.dumps(record).encode()

    with pytest.raises(CandidateJournalError, match="unsafe SQS system attributes"):
        read_terminal_candidates(s3, _config(), "run-1")  # ty: ignore[invalid-argument-type]


def test_candidate_audit_rejects_envelope_identity_tampering() -> None:
    s3 = FakeS3()
    result = _result()
    candidate = write_terminal_candidate(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        run_id="run-1",
        item_id="100/unsafe-path",
        kind="result",
        candidate_body=result.model_dump_json().encode(),
        result=result,
    )
    record = json.loads(s3.objects[candidate.key])
    record["item_id"] = "other"
    s3.objects[candidate.key] = json.dumps(record).encode()

    with pytest.raises(CandidateJournalError, match="identity"):
        read_terminal_candidates(s3, _config(), "run-1")  # ty: ignore[invalid-argument-type]


def test_accept_decision_resolution_round_trip_binds_exact_retained_bodies() -> None:
    s3 = FakeS3()
    result = _result()
    result_body = result.model_dump_json().encode()
    winner = write_terminal_candidate(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        run_id="run-1",
        item_id=result.item_id,
        kind="result",
        candidate_body=result_body,
        result=result,
    )
    decision = claim_terminal_decision(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        candidate=winner,
    )
    s3.objects[decision.canonical_key] = result_body
    failure = _failure()
    rejected = write_terminal_candidate(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        run_id="run-1",
        item_id=failure.item_id,
        kind="failure",
        candidate_body=_failure_body(failure),
        result=failure,
    )

    resolution = write_accept_terminal_decision_resolution(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        run_id="run-1",
        decision_key=decision.key,
        candidate_key=rejected.key,
        expected_decision_sha256=decision.body_sha256,
        expected_candidate_sha256=rejected.candidate_sha256,
        expected_canonical_sha256=hashlib.sha256(result_body).hexdigest(),
        reviewed_at=datetime(2026, 8, 20, 2, tzinfo=UTC),
        reviewed_by="operator@example.com",
        review_note="Portal evidence confirms the conclusive result.",
    )

    assert resolution.candidate_key == rejected.key
    assert resolution.decision_key == decision.key
    assert read_terminal_candidate_resolutions(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        "run-1",
    ) == (resolution,)
    record = json.loads(s3.objects[resolution.key])
    assert record["resolution_type"] == "accept-decision"
    assert record["rejected_candidate_sha256"] == rejected.candidate_sha256

    record["policy_version"] = True
    s3.objects[resolution.key] = json.dumps(record).encode()
    with pytest.raises(CandidateJournalError, match="unsupported policy"):
        read_terminal_candidate_resolutions(  # ty: ignore[invalid-argument-type]
            s3,
            _config(),
            "run-1",
        )


def test_accept_decision_resolution_rejects_stale_review_digest() -> None:
    s3 = FakeS3()
    result = _result()
    body = result.model_dump_json().encode()
    winner = write_terminal_candidate(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        run_id="run-1",
        item_id=result.item_id,
        kind="result",
        candidate_body=body,
        result=result,
    )
    decision = claim_terminal_decision(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        candidate=winner,
    )
    s3.objects[decision.canonical_key] = body
    failure = _failure()
    rejected = write_terminal_candidate(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        run_id="run-1",
        item_id=failure.item_id,
        kind="failure",
        candidate_body=_failure_body(failure),
        result=failure,
    )

    with pytest.raises(ValueError, match="decision body"):
        write_accept_terminal_decision_resolution(  # ty: ignore[invalid-argument-type]
            s3,
            _config(),
            run_id="run-1",
            decision_key=decision.key,
            candidate_key=rejected.key,
            expected_decision_sha256="0" * 64,
            expected_candidate_sha256=rejected.candidate_sha256,
            expected_canonical_sha256=hashlib.sha256(body).hexdigest(),
            reviewed_at=datetime(2026, 8, 20, 2, tzinfo=UTC),
            reviewed_by="operator@example.com",
            review_note="Reviewed exact evidence.",
        )


def test_disposition_round_trip_uses_stable_message_id_across_redelivery() -> None:
    s3 = FakeS3()
    result = _result()
    body = result.model_dump_json().encode()
    original_delivery = {
        "message_id": "message-1",
        "body_sha256": "a" * 64,
        "system_attributes": {"ApproximateReceiveCount": "1"},
    }
    candidate = write_terminal_candidate(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        run_id="run-1",
        item_id="100/unsafe-path",
        kind="result",
        candidate_body=body,
        result=result,
        delivery_metadata=original_delivery,
    )
    disposition = write_terminal_disposition(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        run_id="run-1",
        item_id="100/unsafe-path",
        delivery_metadata=original_delivery,
        candidate=candidate,
        canonical_key="scraper/runs/run-1/results/100/unsafe-path.json",
        canonical_body=body,
        canonical_result=result,
        outcome="created",
    )

    redelivery = write_terminal_disposition(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        run_id="run-1",
        item_id="100/unsafe-path",
        delivery_metadata={
            **original_delivery,
            "system_attributes": {"ApproximateReceiveCount": "3"},
        },
        candidate=candidate,
        canonical_key="scraper/runs/run-1/results/100/unsafe-path.json",
        canonical_body=body,
        canonical_result=result,
        outcome="created",
    )
    assert disposition.receive_count == 1
    assert redelivery == disposition


def test_disposition_rejects_message_body_binding_collision() -> None:
    s3 = FakeS3()
    result = _result()
    body = result.model_dump_json().encode()
    delivery = {
        "message_id": "message-1",
        "body_sha256": "a" * 64,
        "system_attributes": {"ApproximateReceiveCount": "1"},
    }
    candidate = write_terminal_candidate(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        run_id="run-1",
        item_id="100/unsafe-path",
        kind="result",
        candidate_body=body,
        result=result,
        delivery_metadata=delivery,
    )
    write_terminal_disposition(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        run_id="run-1",
        item_id="100/unsafe-path",
        delivery_metadata=delivery,
        candidate=candidate,
        canonical_key="canonical.json",
        canonical_body=body,
        canonical_result=result,
        outcome="duplicate",
    )

    with pytest.raises(CandidateJournalError, match="key collision"):
        write_terminal_disposition(  # ty: ignore[invalid-argument-type]
            s3,
            _config(),
            run_id="run-1",
            item_id="100/unsafe-path",
            delivery_metadata={**delivery, "body_sha256": "b" * 64},
            candidate=candidate,
            canonical_key="canonical.json",
            canonical_body=body,
            canonical_result=result,
            outcome="duplicate",
        )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("schema_version", True, "unsupported schema"),
        ("recorded_at", "2026-08-20T12:00:00", "include a timezone"),
        ("unexpected", "value", "incomplete or unexpected"),
    ],
)
def test_candidate_audit_rejects_untrusted_envelope_schema(
    field: str,
    value: object,
    match: str,
) -> None:
    s3 = FakeS3()
    result = _result()
    candidate = write_terminal_candidate(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        run_id="run-1",
        item_id="100/unsafe-path",
        kind="result",
        candidate_body=result.model_dump_json().encode(),
        result=result,
    )
    record = json.loads(s3.objects[candidate.key])
    record[field] = value
    s3.objects[candidate.key] = json.dumps(record).encode()

    with pytest.raises(CandidateJournalError, match=match):
        read_terminal_candidates(s3, _config(), "run-1")  # ty: ignore[invalid-argument-type]
