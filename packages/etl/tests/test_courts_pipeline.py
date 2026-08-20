"""Tests for courts post-processing helpers."""

from types import SimpleNamespace

import pandas as pd
import pytest
from aws_batch_scraper.aggregate import RunResultConflictError
from aws_batch_scraper.types import ScrapeResult, ScrapeStatus, WorkItem

from etl.courts import pipeline
from etl.courts.config import CourtsWorkerConfig
from etl.courts.pipeline import _merge_flags, _result_coverage, _results_to_flags
from etl.courts.publication import (
    COURTS_PUBLICATION_CONTRACT_VERSION,
    court_flags_sha256,
)


@pytest.fixture(autouse=True)
def _completed_full_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing publication tests exercise an explicitly full completed run."""
    monkeypatch.setattr(
        pipeline,
        "read_run_manifest",
        lambda *args, **kwargs: SimpleNamespace(
            selection_mode="full",
            candidate_count=1,
            input_size=1,
        ),
    )


def test_result_coverage_counts_missing_and_extra_results() -> None:
    input_df = pd.DataFrame({"dc_key": ["100", "200", "300"]})
    results = {
        "100": ScrapeResult(status=ScrapeStatus.SUCCESS),
        "200": ScrapeResult(status=ScrapeStatus.NO_RESULTS),
        "999": ScrapeResult(status=ScrapeStatus.SUCCESS),
    }

    missing_count, extra_count = _result_coverage(results, input_df)

    assert missing_count == 1
    assert extra_count == 1


def test_results_to_flags_keeps_inconclusive_outcomes_unknown() -> None:
    input_df = pd.DataFrame({"dc_key": ["100", "200", "300", "400", "500", "600"]})
    results = {
        "100": ScrapeResult(status=ScrapeStatus.SUCCESS, data={"results": [{"case": "1"}]}),
        "200": ScrapeResult(status=ScrapeStatus.NO_RESULTS),
        "300": ScrapeResult(status=ScrapeStatus.FAILED),
        "400": ScrapeResult(status=ScrapeStatus.INVALID_INPUT),
        "500": ScrapeResult(status=ScrapeStatus.SUCCESS, data={"results": []}),
        "600": ScrapeResult(
            status=ScrapeStatus.NO_RESULTS,
            data={"results": [{"case": "contradicts status"}]},
        ),
    }

    flags = _results_to_flags(results, input_df).set_index("dc_key")["has_court_case"]

    assert bool(flags["100"]) is True
    assert bool(flags["200"]) is False
    assert pd.isna(flags["300"])
    assert pd.isna(flags["400"])
    assert pd.isna(flags["500"])
    assert pd.isna(flags["600"])


def test_merge_flags_preserves_known_values_for_unknown_current_results() -> None:
    existing = pd.DataFrame(
        {"dc_key": ["100", "200", "300"], "has_court_case": [True, False, True]}
    )
    current = pd.DataFrame(
        {
            "dc_key": ["100", "200", "300", "400"],
            "has_court_case": pd.array([pd.NA, True, False, pd.NA], dtype="boolean"),
        }
    )

    merged = _merge_flags(existing, current).set_index("dc_key")["has_court_case"]

    assert bool(merged["100"]) is True  # the unknown observation preserves True
    assert bool(merged["200"]) is True  # a conclusive current hit replaces False
    assert bool(merged["300"]) is False  # a conclusive no-result replaces True
    assert pd.isna(merged["400"])


def test_merge_flags_invalidates_unversioned_legacy_false_but_keeps_true() -> None:
    existing = pd.DataFrame({"dc_key": ["100", "200"], "has_court_case": [True, False]})
    current = pd.DataFrame(
        {
            "dc_key": ["100", "200"],
            "has_court_case": pd.array([pd.NA, pd.NA], dtype="boolean"),
        }
    )

    merged = _merge_flags(existing, current).set_index("dc_key")

    assert bool(merged.loc["100", "has_court_case"]) is True
    assert pd.isna(merged.loc["200", "has_court_case"])
    assert merged["court_search_semantics_version"].eq(2).all()


def test_merge_flags_preserves_versioned_explicit_no_result() -> None:
    existing = pd.DataFrame(
        {
            "dc_key": ["200"],
            "has_court_case": pd.array([False], dtype="boolean"),
            "court_search_semantics_version": [2],
        }
    )
    current = pd.DataFrame(
        {
            "dc_key": ["200"],
            "has_court_case": pd.array([pd.NA], dtype="boolean"),
        }
    )

    merged = _merge_flags(existing, current).set_index("dc_key")

    assert bool(merged.loc["200", "has_court_case"]) is False
    assert merged.loc["200", "court_search_semantics_version"] == 2


def test_forced_failure_uses_current_run_and_preserves_prior_known_flag(
    monkeypatch,
) -> None:
    """A stale global success cannot masquerade as this run's observation."""
    config = CourtsWorkerConfig(
        _env_file=None,
        s3_bucket="bucket",
        aws_account_id="123456789012",
        run_id="run-new",
    )
    current_failure = ScrapeResult(
        status=ScrapeStatus.FAILED,
        item_id="100",
        run_id="run-new",
    )
    read_calls: list[dict[str, object]] = []

    def read_completed_run(*args, **kwargs):
        read_calls.append(kwargs)
        return [WorkItem(item_id="100")]

    monkeypatch.setattr(pipeline, "read_run_items", read_completed_run)
    monkeypatch.setattr(pipeline, "require_no_result_conflicts", lambda *args, **kwargs: None)
    aggregate_calls: list[str | None] = []

    def aggregate_current(*args, run_id=None, **kwargs):
        aggregate_calls.append(run_id)
        return {}

    monkeypatch.setattr(pipeline, "aggregate_results", aggregate_current)
    monkeypatch.setattr(
        pipeline,
        "aggregate_failures",
        lambda *args, **kwargs: {"100": current_failure},
    )
    monkeypatch.setattr(
        pipeline,
        "_read_existing_flags",
        lambda _s3: pd.DataFrame({"dc_key": ["100"], "has_court_case": [True]}),
    )
    monkeypatch.setattr(pipeline, "_write_portal_results", lambda *args, **kwargs: None)
    written: dict[str, object] = {}
    monkeypatch.setattr(
        pipeline,
        "write_processed_csv",
        lambda _name, value, **kwargs: written.update(flags=value.copy()),
    )
    monkeypatch.setattr(
        pipeline,
        "write_meta",
        lambda **kwargs: written.update(meta=kwargs),
    )

    pipeline.process_results(object(), config)  # ty: ignore[invalid-argument-type]

    assert read_calls == [{"require_completed": True}]
    assert aggregate_calls == ["run-new"]
    flags = written["flags"]
    assert isinstance(flags, pd.DataFrame)
    assert bool(flags.set_index("dc_key").loc["100", "has_court_case"]) is True
    meta = written["meta"]
    assert isinstance(meta, dict)
    assert meta["status"] == "partial"
    assert meta["failure_count"] == 1
    assert meta["unknown_result_count"] == 1
    assert meta["missing_result_count"] == 0
    assert meta["publication_contract_version"] == COURTS_PUBLICATION_CONTRACT_VERSION
    assert meta["selection_mode"] == "full"
    assert meta["candidate_count"] == 1
    assert meta["input_count"] == 1
    assert meta["result_count"] == 1
    assert meta["coverage_complete"] is True
    assert meta["flags_row_count"] == len(flags)
    assert meta["flags_sha256"] == court_flags_sha256(flags)
    assert meta["court_search_semantics_version"] == 2


def test_process_results_migrates_legacy_false_to_unknown(
    monkeypatch,
) -> None:
    config = CourtsWorkerConfig(
        _env_file=None,
        s3_bucket="bucket",
        aws_account_id="123456789012",
        run_id="run-new",
    )
    monkeypatch.setattr(
        pipeline,
        "read_run_manifest",
        lambda *args, **kwargs: SimpleNamespace(
            selection_mode="full",
            candidate_count=2,
            input_size=2,
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "read_run_items",
        lambda *args, **kwargs: [WorkItem(item_id="100"), WorkItem(item_id="400")],
    )
    monkeypatch.setattr(pipeline, "require_no_result_conflicts", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "aggregate_results",
        lambda *args, **kwargs: {
            "400": ScrapeResult(
                status=ScrapeStatus.NO_RESULTS,
                item_id="400",
                run_id="run-new",
            )
        },
    )
    monkeypatch.setattr(
        pipeline,
        "aggregate_failures",
        lambda *args, **kwargs: {
            "100": ScrapeResult(
                status=ScrapeStatus.FAILED,
                item_id="100",
                run_id="run-new",
            )
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_read_existing_flags",
        lambda _s3: pd.DataFrame(
            {
                "dc_key": ["100", "200", "300"],
                "has_court_case": [False, False, True],
            }
        ),
    )
    monkeypatch.setattr(pipeline, "_write_portal_results", lambda *args, **kwargs: None)
    written: dict[str, object] = {}
    monkeypatch.setattr(
        pipeline,
        "write_processed_csv",
        lambda _name, value, **kwargs: written.update(flags=value.copy()),
    )
    monkeypatch.setattr(pipeline, "write_meta", lambda **kwargs: written.update(meta=kwargs))

    pipeline.process_results(object(), config)  # ty: ignore[invalid-argument-type]

    flags = written["flags"]
    assert isinstance(flags, pd.DataFrame)
    by_id = flags.set_index("dc_key")
    assert pd.isna(by_id.loc["100", "has_court_case"])
    assert pd.isna(by_id.loc["200", "has_court_case"])
    assert bool(by_id.loc["300", "has_court_case"]) is True
    assert bool(by_id.loc["400", "has_court_case"]) is False
    assert by_id["court_search_semantics_version"].eq(2).all()


def test_process_results_rejects_records_outside_immutable_input(
    monkeypatch,
) -> None:
    config = CourtsWorkerConfig(
        _env_file=None,
        s3_bucket="bucket",
        aws_account_id="123456789012",
        run_id="run-new",
    )
    monkeypatch.setattr(
        pipeline,
        "read_run_items",
        lambda *args, **kwargs: [WorkItem(item_id="100")],
    )
    monkeypatch.setattr(pipeline, "require_no_result_conflicts", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "aggregate_results",
        lambda *args, **kwargs: {
            item_id: ScrapeResult(
                status=ScrapeStatus.NO_RESULTS,
                item_id=item_id,
                run_id="run-new",
            )
            for item_id in ("100", "999")
        },
    )
    monkeypatch.setattr(pipeline, "aggregate_failures", lambda *args, **kwargs: {})
    writes: list[str] = []
    monkeypatch.setattr(
        pipeline,
        "_write_portal_results",
        lambda *args, **kwargs: writes.append("portal"),
    )
    monkeypatch.setattr(
        pipeline,
        "write_processed_csv",
        lambda *args, **kwargs: writes.append("flags"),
    )

    with pytest.raises(ValueError, match="outside its immutable input set.*999"):
        pipeline.process_results(object(), config)  # ty: ignore[invalid-argument-type]

    assert writes == []


def test_process_results_refuses_conflicted_run_before_aggregation_or_writes(
    monkeypatch,
) -> None:
    config = CourtsWorkerConfig(
        _env_file=None,
        s3_bucket="bucket",
        aws_account_id="123456789012",
        run_id="run-new",
    )
    monkeypatch.setattr(
        pipeline,
        "read_run_items",
        lambda *args, **kwargs: [WorkItem(item_id="100")],
    )
    calls: list[str] = []

    def reject_conflicts(*args, **kwargs) -> None:
        calls.append("conflict-check")
        raise RunResultConflictError("conflicting result")

    monkeypatch.setattr(pipeline, "require_no_result_conflicts", reject_conflicts)
    monkeypatch.setattr(
        pipeline,
        "aggregate_results",
        lambda *args, **kwargs: calls.append("aggregate-results"),
    )
    monkeypatch.setattr(
        pipeline,
        "aggregate_failures",
        lambda *args, **kwargs: calls.append("aggregate-failures"),
    )
    monkeypatch.setattr(
        pipeline,
        "_write_portal_results",
        lambda *args, **kwargs: calls.append("portal-write"),
    )
    monkeypatch.setattr(
        pipeline,
        "write_processed_csv",
        lambda *args, **kwargs: calls.append("flags-write"),
    )

    with pytest.raises(RunResultConflictError, match="conflicting result"):
        pipeline.process_results(object(), config)  # ty: ignore[invalid-argument-type]

    assert calls == ["conflict-check"]


@pytest.mark.parametrize("selection_mode", ["sample", "incremental"])
def test_non_full_run_validates_results_without_mutating_stable_processed_objects(
    monkeypatch: pytest.MonkeyPatch,
    selection_mode: str,
) -> None:
    config = CourtsWorkerConfig(
        _env_file=None,
        s3_bucket="bucket",
        aws_account_id="123456789012",
        run_id="run-non-full",
    )
    monkeypatch.setattr(
        pipeline,
        "read_run_manifest",
        lambda *args, **kwargs: SimpleNamespace(
            selection_mode=selection_mode,
            candidate_count=100,
            input_size=1,
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "read_run_items",
        lambda *args, **kwargs: [WorkItem(item_id="100")],
    )
    monkeypatch.setattr(pipeline, "require_no_result_conflicts", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "aggregate_results",
        lambda *args, **kwargs: {
            "100": ScrapeResult(
                status=ScrapeStatus.NO_RESULTS,
                item_id="100",
                run_id="run-non-full",
            )
        },
    )
    monkeypatch.setattr(pipeline, "aggregate_failures", lambda *args, **kwargs: {})
    stable_calls: list[str] = []
    monkeypatch.setattr(
        pipeline,
        "_write_portal_results",
        lambda *args, **kwargs: stable_calls.append("portal_results"),
    )
    monkeypatch.setattr(
        pipeline,
        "_read_existing_flags",
        lambda *args, **kwargs: stable_calls.append("read_existing_flags"),
    )
    monkeypatch.setattr(
        pipeline,
        "write_processed_csv",
        lambda *args, **kwargs: stable_calls.append("courts_flags"),
    )
    monkeypatch.setattr(
        pipeline,
        "write_meta",
        lambda *args, **kwargs: stable_calls.append("courts_meta"),
    )

    pipeline.process_results(object(), config)  # ty: ignore[invalid-argument-type]

    assert stable_calls == []


def test_incomplete_full_run_cannot_replace_stable_processed_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = CourtsWorkerConfig(
        _env_file=None,
        s3_bucket="bucket",
        aws_account_id="123456789012",
        run_id="run-incomplete-full",
    )
    monkeypatch.setattr(
        pipeline,
        "read_run_manifest",
        lambda *args, **kwargs: SimpleNamespace(
            selection_mode="full",
            candidate_count=2,
            input_size=2,
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "read_run_items",
        lambda *args, **kwargs: [WorkItem(item_id="100"), WorkItem(item_id="200")],
    )
    monkeypatch.setattr(pipeline, "require_no_result_conflicts", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "aggregate_results",
        lambda *args, **kwargs: {
            "100": ScrapeResult(
                status=ScrapeStatus.NO_RESULTS,
                item_id="100",
                run_id="run-incomplete-full",
            )
        },
    )
    monkeypatch.setattr(pipeline, "aggregate_failures", lambda *args, **kwargs: {})
    stable_calls: list[str] = []
    monkeypatch.setattr(
        pipeline,
        "_write_portal_results",
        lambda *args, **kwargs: stable_calls.append("portal_results"),
    )
    monkeypatch.setattr(
        pipeline,
        "_read_existing_flags",
        lambda *args, **kwargs: stable_calls.append("read_existing_flags"),
    )
    monkeypatch.setattr(
        pipeline,
        "write_processed_csv",
        lambda *args, **kwargs: stable_calls.append("courts_flags"),
    )
    monkeypatch.setattr(
        pipeline,
        "write_meta",
        lambda *args, **kwargs: stable_calls.append("courts_meta"),
    )

    with pytest.raises(ValueError, match="complete terminal result coverage"):
        pipeline.process_results(object(), config)  # ty: ignore[invalid-argument-type]

    assert stable_calls == []
