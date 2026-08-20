"""Tests for queue-envelope validation and message-scoped behavior."""

import base64
import hashlib
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import Any, cast
from unittest.mock import MagicMock

import aws_batch_scraper.worker as worker_module
import pytest
from aws_batch_scraper.config import WorkerConfig
from aws_batch_scraper.queue import seed_queue
from aws_batch_scraper.types import ScrapeResult, ScrapeStatus, WorkItem
from aws_batch_scraper.worker import (
    ResultPublicationConflict,
    _parse_work_message,
    _quarantine_invalid_message,
    _quarantine_result_conflict,
    _queue_is_empty,
    _read_work_message,
    _sqs_delivery_metadata,
    _write_failure,
    _write_result,
)
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


class FakeSQS:
    def __init__(self) -> None:
        self.batch_requests: list[dict[str, object]] = []
        self.sent_messages: list[dict[str, str]] = []
        self.deleted_messages: list[dict[str, str]] = []

    def send_message_batch(self, *, QueueUrl, Entries):
        self.batch_requests.append({"QueueUrl": QueueUrl, "Entries": Entries})
        return {
            "Successful": [{"Id": entry["Id"], "MessageId": entry["Id"]} for entry in Entries],
            "Failed": [],
        }

    def send_message(self, *, QueueUrl, MessageBody):
        self.sent_messages.append({"QueueUrl": QueueUrl, "MessageBody": MessageBody})
        return {"MessageId": "message-1"}

    def delete_message(self, *, QueueUrl, ReceiptHandle):
        self.deleted_messages.append({"QueueUrl": QueueUrl, "ReceiptHandle": ReceiptHandle})


def _client_error(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


class ConditionalFakeS3:
    """Thread-safe in-memory S3 fake with PutObject preconditions."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[dict[str, object]] = []
        self._lock = threading.Lock()

    def put_object(self, **kwargs):
        key = kwargs["Key"]
        assert isinstance(key, str)
        with self._lock:
            if kwargs.get("IfNoneMatch") == "*" and key in self.objects:
                raise _client_error("PreconditionFailed", "PutObject")
            body = kwargs["Body"]
            assert isinstance(body, bytes)
            self.objects[key] = body
            self.puts.append(kwargs)
        return {"ETag": '"etag"'}

    def get_object(self, *, Bucket, Key):
        with self._lock:
            body = self.objects[Key]
        return {"Body": BytesIO(body)}


def _result_conflict_keys(s3: ConditionalFakeS3) -> list[str]:
    return sorted(key for key in s3.objects if "/result-conflicts/" in key)


def test_seed_queue_carries_force_on_each_message() -> None:
    sqs = FakeSQS()

    seed_queue(
        sqs,
        _config(),
        [WorkItem(item_id="1", extra={"source": "test"})],
        "run-1",
        force_rescrape=True,
    )

    entries = sqs.batch_requests[0]["Entries"]
    assert isinstance(entries, list)
    body = json.loads(entries[0]["MessageBody"])
    assert body == {
        "item_id": "1",
        "run_id": "run-1",
        "force_rescrape": True,
        "source": "test",
    }


@pytest.mark.parametrize("reserved", ["item_id", "run_id", "force_rescrape"])
def test_work_item_rejects_reserved_extra_fields(reserved: str) -> None:
    with pytest.raises(ValueError, match="reserved queue field"):
        WorkItem(item_id="1", extra={reserved: "collision"})


def test_seed_queue_rechecks_mutated_work_item() -> None:
    item = WorkItem(item_id="1")
    item.extra["run_id"] = "shadowed"

    with pytest.raises(ValueError, match="reserved queue field"):
        seed_queue(FakeSQS(), _config(), [item], "run-1")


@pytest.mark.parametrize(
    "item",
    [
        lambda: WorkItem(item_id=cast(Any, 1)),
        lambda: WorkItem(item_id="1", extra=cast(Any, [])),
        lambda: WorkItem(item_id="1", extra=cast(dict[str, Any], {1: "value"})),
    ],
)
def test_work_item_validates_plugin_runtime_types(item: object) -> None:
    with pytest.raises(TypeError):
        cast(Any, item)()


def test_seed_queue_validates_all_items_before_first_batch() -> None:
    sqs = FakeSQS()
    items = [WorkItem(item_id=str(index)) for index in range(11)]
    items[-1].extra["run_id"] = "shadowed"

    with pytest.raises(ValueError, match="reserved queue field"):
        seed_queue(sqs, _config(), items, "run-1")

    assert sqs.batch_requests == []


def test_seed_queue_rejects_duplicate_ids_before_first_batch() -> None:
    sqs = FakeSQS()

    with pytest.raises(ValueError, match="duplicate item IDs"):
        seed_queue(
            sqs,
            _config(),
            [WorkItem(item_id="1"), WorkItem(item_id="1")],
            "run-1",
        )

    assert sqs.batch_requests == []


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, object(), ("tuple",)])
def test_work_item_extra_requires_strict_json_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        WorkItem(item_id="1", extra={"value": value})


def test_work_item_extra_rejects_cycles() -> None:
    extra: dict[str, object] = {}
    extra["cycle"] = extra

    with pytest.raises(ValueError, match="cyclic JSON"):
        WorkItem(item_id="1", extra=extra)


def test_parse_work_message_validates_boundary_and_preserves_extra() -> None:
    message = _parse_work_message(
        json.dumps(
            {
                "item_id": "1",
                "run_id": "run-1",
                "force_rescrape": True,
                "source": "test",
            }
        ),
        "fallback-run",
    )

    assert message.force_rescrape is True
    assert message.to_work_item() == WorkItem(item_id="1", extra={"source": "test"})
    with pytest.raises(ValueError):
        _parse_work_message("not json", "run-1")
    with pytest.raises(ValueError):
        _parse_work_message(json.dumps({"run_id": "run-1"}), "run-1")
    with pytest.raises(ValueError, match="missing run_id"):
        _parse_work_message(json.dumps({"item_id": "1"}), "run-1")
    with pytest.raises(ValueError, match="duplicate JSON field: item_id"):
        _parse_work_message(
            '{"item_id":"1","item_id":"2","run_id":"run-1"}',
            "run-1",
        )
    with pytest.raises(ValueError):
        _parse_work_message(
            '{"item_id":"1","run_id":"run-1","force_rescrape":"false"}',
            "run-1",
        )


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_parse_work_message_rejects_nonstandard_json_numbers(constant: str) -> None:
    raw_body = f'{{"item_id":"1","run_id":"run-1","value":{constant}}}'

    with pytest.raises(ValueError, match="non-standard JSON constant"):
        _parse_work_message(raw_body, "run-1")


def test_quarantine_invalid_message_copies_before_delete() -> None:
    sqs = FakeSQS()
    raw_body = "not json"

    _quarantine_invalid_message(
        sqs,
        _config(),
        {"Body": raw_body, "ReceiptHandle": "receipt-1"},
        ValueError("bad body"),
    )

    assert sqs.sent_messages[0]["MessageBody"] == raw_body
    assert sqs.deleted_messages == [
        {"QueueUrl": _config().sqs_queue_url, "ReceiptHandle": "receipt-1"}
    ]


def test_quarantine_result_conflict_copies_before_delete() -> None:
    sqs = FakeSQS()
    raw_body = json.dumps({"item_id": "1", "run_id": "run-1"})

    _quarantine_result_conflict(
        sqs,
        _config(),
        {"Body": raw_body, "ReceiptHandle": "receipt-1"},
        ResultPublicationConflict("opposite conclusions"),
    )

    assert sqs.sent_messages == [{"QueueUrl": _config().sqs_dlq_url, "MessageBody": raw_body}]
    assert sqs.deleted_messages == [
        {"QueueUrl": _config().sqs_queue_url, "ReceiptHandle": "receipt-1"}
    ]


def test_result_conflict_dlq_failure_leaves_source_message_for_redelivery() -> None:
    class FailingSQS(FakeSQS):
        def send_message(self, *, QueueUrl, MessageBody):
            raise RuntimeError("DLQ unavailable")

    sqs = FailingSQS()
    raw_body = json.dumps({"item_id": "1", "run_id": "run-1"})

    with pytest.raises(RuntimeError, match="DLQ unavailable"):
        _quarantine_result_conflict(
            sqs,
            _config(),
            {"Body": raw_body, "ReceiptHandle": "receipt-1"},
            ResultPublicationConflict("opposite conclusions"),
        )

    assert sqs.deleted_messages == []


def test_deeply_nested_json_is_quarantined_inside_message_boundary() -> None:
    sqs = FakeSQS()
    raw_body = '{"item_id":"1","run_id":"run-1","nested":' + "[" * 2_000
    raw_body += "0" + "]" * 2_000 + "}"

    parsed = _read_work_message(
        sqs,
        _config(),
        {"Body": raw_body, "ReceiptHandle": "receipt-1"},
        "run-1",
    )

    assert parsed is None
    assert sqs.sent_messages[0]["MessageBody"] == raw_body
    assert sqs.deleted_messages[0]["ReceiptHandle"] == "receipt-1"


def test_foreign_run_message_is_quarantined_without_processing() -> None:
    sqs = FakeSQS()
    raw_body = json.dumps({"item_id": "1", "run_id": "run-foreign"})

    parsed = _read_work_message(
        sqs,
        _config(),
        {"Body": raw_body, "ReceiptHandle": "receipt-1"},
        "run-owned",
    )

    assert parsed is None
    assert sqs.sent_messages == [{"QueueUrl": _config().sqs_dlq_url, "MessageBody": raw_body}]
    assert sqs.deleted_messages == [
        {"QueueUrl": _config().sqs_queue_url, "ReceiptHandle": "receipt-1"}
    ]


def test_worker_queue_empty_requires_zero_delayed_messages() -> None:
    sqs = MagicMock()
    sqs.get_queue_attributes.return_value = {
        "Attributes": {
            "ApproximateNumberOfMessages": "0",
            "ApproximateNumberOfMessagesNotVisible": "0",
            "ApproximateNumberOfMessagesDelayed": "1",
        }
    }

    assert _queue_is_empty(sqs, _config()) is False
    assert (
        "ApproximateNumberOfMessagesDelayed"
        in (sqs.get_queue_attributes.call_args.kwargs["AttributeNames"])
    )


def test_sqs_delivery_evidence_excludes_receipt_handle_and_raw_body() -> None:
    raw_body = json.dumps({"item_id": "100", "run_id": "run-new"})

    evidence = _sqs_delivery_metadata(  # ty: ignore[invalid-argument-type]
        {
            "MessageId": "message-1",
            "MD5OfBody": "body-md5",
            "Body": raw_body,
            "ReceiptHandle": "secret-capability",
            "Attributes": {
                "ApproximateReceiveCount": "2",
                "SentTimestamp": "1234",
                "AWSTraceHeader": "not-persisted",
            },
        }
    )

    assert evidence == {
        "message_id": "message-1",
        "md5_of_body": "body-md5",
        "body_sha256": hashlib.sha256(raw_body.encode()).hexdigest(),
        "system_attributes": {
            "ApproximateReceiveCount": "2",
            "SentTimestamp": "1234",
        },
    }


def test_conclusive_result_is_written_to_run_scope_before_global_cache() -> None:
    s3 = ConditionalFakeS3()
    result = ScrapeResult(status=ScrapeStatus.NO_RESULTS)

    outcome = _write_result(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        "100",
        "run-new",
        result,
        "scraper/results/100.json",
    )

    assert outcome == "created"
    assert [put["Key"] for put in s3.puts] == [
        "scraper/runs/run-new/results/100.json",
        "scraper/results/100.json",
    ]
    assert s3.puts[0]["IfNoneMatch"] == "*"
    assert result.run_id == "run-new"


def test_conditional_409_propagates_without_assuming_a_canonical_result() -> None:
    class ConditionalConflictS3(ConditionalFakeS3):
        def put_object(self, **kwargs):
            if kwargs.get("IfNoneMatch") == "*" and kwargs["Key"].endswith("/results/100.json"):
                raise _client_error("ConditionalRequestConflict", "PutObject")
            return super().put_object(**kwargs)

    s3 = ConditionalConflictS3()

    with pytest.raises(ClientError) as caught:
        _write_result(  # ty: ignore[invalid-argument-type]
            s3,
            _config(),
            "100",
            "run-new",
            ScrapeResult(status=ScrapeStatus.NO_RESULTS),
            "scraper/results/100.json",
        )

    assert caught.value.response["Error"]["Code"] == "ConditionalRequestConflict"
    assert s3.objects == {}
    assert s3.puts == []


def test_identical_duplicate_keeps_first_exact_body_and_refreshes_cache_from_it() -> None:
    s3 = ConditionalFakeS3()
    first = ScrapeResult(
        status=ScrapeStatus.NO_RESULTS,
        classification="explicit-no-results",
        attempt_count=1,
        scrape_duration_s=0.1,
        extra={"status_histogram": {"200": 10}},
    )
    duplicate = ScrapeResult(
        status=ScrapeStatus.NO_RESULTS,
        classification="explicit-no-results",
        attempt_count=4,
        scrape_duration_s=9.9,
        extra={"status_histogram": {"200": 12}},
    )

    assert (
        _write_result(  # ty: ignore[invalid-argument-type]
            s3,
            _config(),
            "100",
            "run-new",
            first,
            "scraper/results/100.json",
        )
        == "created"
    )
    exact_key = "scraper/runs/run-new/results/100.json"
    first_body = s3.objects[exact_key]

    assert (
        _write_result(  # ty: ignore[invalid-argument-type]
            s3,
            _config(),
            "100",
            "run-new",
            duplicate,
            "scraper/results/100.json",
        )
        == "duplicate"
    )

    assert s3.objects[exact_key] == first_body
    assert s3.objects["scraper/results/100.json"] == first_body
    assert _result_conflict_keys(s3) == []


@pytest.mark.parametrize(
    "result",
    [
        ScrapeResult(status=ScrapeStatus.NO_RESULTS, is_soft_blocked=True),
        ScrapeResult(status=ScrapeStatus.NO_RESULTS, is_network_error=True),
    ],
)
def test_conclusive_result_with_retry_hint_is_rejected(result: ScrapeResult) -> None:
    s3 = ConditionalFakeS3()

    with pytest.raises(ValueError, match="still carries a retry hint"):
        _write_result(  # ty: ignore[invalid-argument-type]
            s3,
            _config(),
            "100",
            "run-new",
            result,
            "scraper/results/100.json",
        )

    assert s3.objects == {}


@pytest.mark.parametrize(
    "candidate",
    [
        ScrapeResult(
            status=ScrapeStatus.SUCCESS,
            data={"results": [{"case": "2"}]},
            classification="found",
            subreason="exact",
        ),
        ScrapeResult(
            status=ScrapeStatus.SUCCESS,
            data={"results": [{"case": "1"}]},
            classification="different",
            subreason="exact",
        ),
        ScrapeResult(
            status=ScrapeStatus.SUCCESS,
            data={"results": [{"case": "1"}]},
            classification="found",
            subreason="different",
        ),
    ],
)
def test_each_semantic_field_mismatch_remains_a_conflict(candidate: ScrapeResult) -> None:
    s3 = ConditionalFakeS3()
    _write_result(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        "100",
        "run-new",
        ScrapeResult(
            status=ScrapeStatus.SUCCESS,
            data={"results": [{"case": "1"}]},
            classification="found",
            subreason="exact",
        ),
        "scraper/results/100.json",
    )

    with pytest.raises(ResultPublicationConflict):
        _write_result(  # ty: ignore[invalid-argument-type]
            s3,
            _config(),
            "100",
            "run-new",
            candidate,
            "scraper/results/100.json",
        )

    assert len(_result_conflict_keys(s3)) == 1


def test_conflicting_duplicate_is_durable_and_cannot_replace_first_result() -> None:
    s3 = ConditionalFakeS3()
    first = ScrapeResult(status=ScrapeStatus.NO_RESULTS)
    conflicting = ScrapeResult(
        status=ScrapeStatus.SUCCESS,
        data={"results": [{"case": "1"}]},
    )
    _write_result(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        "100",
        "run-new",
        first,
        "scraper/results/100.json",
    )
    exact_key = "scraper/runs/run-new/results/100.json"
    first_body = s3.objects[exact_key]

    with pytest.raises(ResultPublicationConflict, match="durable conflict evidence"):
        _write_result(  # ty: ignore[invalid-argument-type]
            s3,
            _config(),
            "100",
            "run-new",
            conflicting,
            "scraper/results/100.json",
            delivery_metadata={
                "message_id": "message-2",
                "system_attributes": {"ApproximateReceiveCount": "2"},
            },
        )

    assert s3.objects[exact_key] == first_body
    assert s3.objects["scraper/results/100.json"] == first_body
    conflict_key = _result_conflict_keys(s3)[0]
    assert conflict_key.startswith("scraper/runs/run-new/result-conflicts/v2/100/")
    conflict = json.loads(s3.objects[conflict_key])
    assert conflict["schema_version"] == 2
    assert conflict["terminal_status"] == "result-conflict"
    assert conflict["existing_status"] == "NO_RESULTS"
    assert conflict["candidate_status"] == "SUCCESS"
    assert {"status", "data"}.issubset(conflict["differing_fields"])
    assert conflict["existing_evidence"]["semantic_observation"]["status"] == "NO_RESULTS"
    assert conflict["candidate_evidence"]["semantic_observation"]["status"] == "SUCCESS"
    candidate_body = base64.b64decode(conflict["candidate_evidence"]["body_base64"])
    assert hashlib.sha256(candidate_body).hexdigest() == conflict["candidate_sha256"]
    assert json.loads(candidate_body)["status"] == "SUCCESS"
    assert conflict["sqs_delivery"] == {
        "message_id": "message-2",
        "system_attributes": {"ApproximateReceiveCount": "2"},
    }
    conflict_put = next(put for put in s3.puts if put["Key"] == conflict_key)
    assert conflict_put["IfNoneMatch"] == "*"


def test_opposite_results_racing_for_one_item_have_one_winner_and_one_conflict() -> None:
    s3 = ConditionalFakeS3()

    def publish(result: ScrapeResult) -> str:
        try:
            return _write_result(  # ty: ignore[invalid-argument-type]
                s3,
                _config(),
                "100",
                "run-new",
                result,
                "scraper/results/100.json",
            )
        except ResultPublicationConflict:
            return "conflict"

    candidates = [
        ScrapeResult(status=ScrapeStatus.NO_RESULTS),
        ScrapeResult(status=ScrapeStatus.SUCCESS, data={"results": [{"case": "1"}]}),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(publish, candidates))

    assert sorted(outcomes) == ["conflict", "created"]
    exact = ScrapeResult.model_validate_json(s3.objects["scraper/runs/run-new/results/100.json"])
    cached = ScrapeResult.model_validate_json(s3.objects["scraper/results/100.json"])
    assert cached.status == exact.status
    assert cached.data == exact.data
    assert len(_result_conflict_keys(s3)) == 1


def test_distinct_candidate_conflicts_are_each_preserved_append_only() -> None:
    s3 = ConditionalFakeS3()
    _write_result(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        "100",
        "run-new",
        ScrapeResult(status=ScrapeStatus.NO_RESULTS),
        "scraper/results/100.json",
    )

    for case in ("1", "2"):
        with pytest.raises(ResultPublicationConflict):
            _write_result(  # ty: ignore[invalid-argument-type]
                s3,
                _config(),
                "100",
                "run-new",
                ScrapeResult(
                    status=ScrapeStatus.SUCCESS,
                    data={"results": [{"case": case}]},
                ),
                "scraper/results/100.json",
            )

    conflict_keys = _result_conflict_keys(s3)
    assert len(conflict_keys) == 2
    assert all("/result-conflicts/v2/100/" in key for key in conflict_keys)
    assert len({json.loads(s3.objects[key])["candidate_sha256"] for key in conflict_keys}) == 2


@pytest.mark.parametrize(
    "existing_body",
    [
        b"not-json",
        b'{"status":"NO_RESULTS","status":"SUCCESS","item_id":"100","run_id":"run-new"}',
        b'{"status":"NO_RESULTS","data":{"results":[],"results":[1]},"item_id":"100","run_id":"run-new"}',
    ],
)
def test_invalid_preexisting_exact_result_records_terminal_conflict(
    existing_body: bytes,
) -> None:
    s3 = ConditionalFakeS3()
    exact_key = "scraper/runs/run-new/results/100.json"
    s3.objects[exact_key] = existing_body

    with pytest.raises(ResultPublicationConflict, match="durable conflict evidence"):
        _write_result(  # ty: ignore[invalid-argument-type]
            s3,
            _config(),
            "100",
            "run-new",
            ScrapeResult(status=ScrapeStatus.NO_RESULTS),
            "scraper/results/100.json",
        )

    assert s3.objects[exact_key] == existing_body
    conflict = json.loads(s3.objects[_result_conflict_keys(s3)[0]])
    assert conflict["reason"] == "existing exact-run result is invalid"
    assert conflict["differing_fields"] == ["existing_result_invalid"]


def test_worker_terminalizes_conflicting_duplicate_only_after_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s3 = ConditionalFakeS3()
    sqs = FakeSQS()
    exact_key = "scraper/runs/run-new/results/100.json"
    first = ScrapeResult(
        status=ScrapeStatus.NO_RESULTS,
        item_id="100",
        run_id="run-new",
    )
    first_body = first.model_dump_json().encode()
    s3.objects[exact_key] = first_body

    class FakeSession:
        def client(self, service: str):
            return s3 if service == "s3" else sqs

    class FakeScraper:
        def __call__(self, item: WorkItem) -> ScrapeResult:
            return ScrapeResult(
                status=ScrapeStatus.SUCCESS,
                data={"results": [{"case": "1"}]},
            )

        def reset(self) -> None:
            return None

        def close(self) -> None:
            return None

    message = {
        "Body": json.dumps(
            {
                "item_id": "100",
                "run_id": "run-new",
                "force_rescrape": True,
            }
        ),
        "ReceiptHandle": "receipt-1",
    }
    messages = iter([message, None, None, None])
    monkeypatch.setattr(worker_module, "make_boto3_session", lambda **kwargs: FakeSession())
    monkeypatch.setattr(worker_module, "_receive_message", lambda *args: next(messages))
    monkeypatch.setattr(worker_module, "_queue_is_empty", lambda *args: True)
    monkeypatch.setattr(worker_module.random, "uniform", lambda *args: 0.0)
    monkeypatch.setattr(worker_module.time, "sleep", lambda *args: None)
    monkeypatch.setattr(worker_module.signal, "signal", lambda *args: None)
    monkeypatch.setattr(worker_module.signal, "alarm", lambda *args: 0)

    worker_module.run_worker(
        lambda: FakeScraper(), _config().model_copy(update={"run_id": "run-new"})
    )

    assert s3.objects[exact_key] == first_body
    assert len(_result_conflict_keys(s3)) == 1
    assert sqs.sent_messages == [
        {"QueueUrl": _config().sqs_dlq_url, "MessageBody": message["Body"]}
    ]
    assert sqs.deleted_messages == [
        {"QueueUrl": _config().sqs_queue_url, "ReceiptHandle": "receipt-1"}
    ]
    stats_keys = [key for key in s3.objects if key.endswith("-stats.json")]
    assert len(stats_keys) == 1
    assert json.loads(s3.objects[stats_keys[0]])["permanent_failure_count"] == 1


def test_failure_artifact_carries_exact_run_identity() -> None:
    class FakeS3:
        def __init__(self) -> None:
            self.puts: list[dict[str, object]] = []

        def put_object(self, **kwargs):
            self.puts.append(kwargs)

    s3 = FakeS3()

    _write_failure(  # ty: ignore[invalid-argument-type]
        s3,
        _config(),
        "run-new",
        "100",
        ScrapeResult(status=ScrapeStatus.FAILED),
    )

    body = json.loads(s3.puts[0]["Body"])
    assert body["run_id"] == "run-new"
    assert body["item_id"] == "100"
