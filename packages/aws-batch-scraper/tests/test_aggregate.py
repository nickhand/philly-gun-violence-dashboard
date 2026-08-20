"""Contracts for exact-run manifest and input aggregation."""

import json
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from aws_batch_scraper.aggregate import (
    RunManifest,
    RunResultConflictError,
    aggregate_results,
    read_run_items,
    read_run_manifest,
    require_no_result_conflicts,
)
from aws_batch_scraper.config import WorkerConfig
from aws_batch_scraper.types import ScrapeResult, ScrapeStatus, WorkItem
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


def _s3_with_results(objects: dict[str, bytes | Exception]) -> MagicMock:
    class Paginator:
        def paginate(self, **kwargs):
            return [
                {
                    "Contents": [{"Key": key} for key in objects],
                }
            ]

    s3 = MagicMock()
    s3.get_paginator.return_value = Paginator()

    def get_object(*, Bucket: str, Key: str) -> dict[str, BytesIO]:
        value = objects[Key]
        if isinstance(value, Exception):
            raise value
        return {"Body": BytesIO(value)}

    s3.get_object.side_effect = get_object
    return s3


def _result(*, item_id: str = "100", run_id: str = "run-1") -> bytes:
    result = ScrapeResult(
        status=ScrapeStatus.NO_RESULTS,
        item_id=item_id,
        run_id=run_id,
    )
    return result.model_dump_json().encode()


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
    ],
)
def test_exact_run_aggregation_fails_closed_on_invalid_result(body: bytes) -> None:
    s3 = _s3_with_results({"scraper/runs/run-1/results/100.json": body})

    with pytest.raises(ValidationError):
        aggregate_results(s3, _config(), run_id="run-1")


def test_result_conflict_evidence_blocks_exact_run_publication() -> None:
    conflict_key = "scraper/runs/run-1/result-conflicts/100.json"
    s3 = _s3_with_results({conflict_key: b'{"terminal_status":"result-conflict"}'})

    with pytest.raises(RunResultConflictError, match="Refusing to aggregate or publish"):
        require_no_result_conflicts(s3, _config(), "run-1")


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
