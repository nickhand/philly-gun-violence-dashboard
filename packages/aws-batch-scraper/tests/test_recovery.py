"""Contracts for selective, same-run scraper recovery."""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from unittest.mock import ANY, MagicMock

import pytest
from aws_batch_scraper import aggregate, recovery, terminal_journal
from aws_batch_scraper.aggregate import ResultConflictReport
from aws_batch_scraper.config import SubmitterConfig, WorkerConfig
from aws_batch_scraper.lease import RunLease
from aws_batch_scraper.recovery import (
    QueueState,
    RecoveryAction,
    RecoveryInvariantError,
    RecoveryInventory,
    RecoveryPlan,
    build_recovery_plan,
    execute_recovery_plan,
    inventory_run,
    read_prior_task_arns,
    reconcile_recovery_attempt,
    require_prior_tasks_stopped,
    require_stable_queue_state,
    write_recovery_plan,
    write_recovery_tasks,
)
from aws_batch_scraper.result_semantics import semantic_observation
from aws_batch_scraper.terminal_journal import (
    CandidateJournalError,
    TerminalCandidate,
    TerminalCandidateResolution,
    TerminalDecisionConflict,
)
from aws_batch_scraper.types import ScrapeResult, ScrapeStatus, WorkItem


def _config() -> WorkerConfig:
    return WorkerConfig(
        _env_file=None,
        s3_bucket="bucket",
        s3_scraper_prefix="scraper",
        aws_account_id="123456789012",
        sqs_queue_name="queue",
        sqs_dlq_name="queue-dlq",
    )


def _submitter_config() -> SubmitterConfig:
    return SubmitterConfig(
        _env_file=None,
        s3_bucket="bucket",
        s3_scraper_prefix="scraper",
        aws_account_id="123456789012",
        sqs_queue_name="queue",
        sqs_dlq_name="queue-dlq",
        ecs_cluster_name="cluster",
        ecs_task_definition="task:1",
        ecs_monitor_task_definition="monitor:1",
        ecs_expected_image_uri=(
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/scraper@sha256:" + "a" * 64
        ),
        ecs_expected_task_role_arn="arn:aws:iam::123456789012:role/task",
        ecs_expected_execution_role_arn="arn:aws:iam::123456789012:role/execution",
        ecs_expected_monitor_secret_arn=(
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:monitor-AbCdEf"
        ),
        ecs_platform_version="1.4.0",
        github_repository="owner/repository",
        github_workflow_file="process.yml",
        ecs_container_name="worker",
        ecs_subnet_ids=["subnet-1"],
        ecs_security_group_ids=["sg-1"],
    )


def _result(item_id: str, status: ScrapeStatus) -> ScrapeResult:
    return ScrapeResult(status=status, item_id=item_id, run_id="run-1")


def _candidate(
    result: ScrapeResult,
    kind: str = "result",
    digest_character: str = "e",
) -> TerminalCandidate:
    body = result.model_dump_json().encode()
    return TerminalCandidate(
        key=f"candidate-{result.item_id}-{kind}-{digest_character}",
        run_id="run-1",
        item_id=str(result.item_id),
        kind=kind,  # ty: ignore[invalid-argument-type]
        candidate_sha256=digest_character * 64,
        observation_sha256="f" * 64,
        candidate_body=body,
        result=result,
    )


def _empty_conflicts(
    *,
    unresolved: int = 0,
    invalid_resolutions: int = 0,
    resolved_keys: tuple[str, ...] = (),
) -> ResultConflictReport:
    return ResultConflictReport(
        conflict_policy_version=1,
        total_count=unresolved + len(resolved_keys),
        resolved_count=len(resolved_keys),
        unresolved_count=unresolved,
        evidence_sha256="c" * 64,
        resolved_keys=resolved_keys,
        unresolved_keys=tuple(f"conflict-{index}" for index in range(unresolved)),
        invalid_resolution_count=invalid_resolutions,
        invalid_resolution_keys=tuple(
            f"resolution-{index}" for index in range(invalid_resolutions)
        ),
    )


def _patch_inventory_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    results: dict[str, ScrapeResult] | None = None,
    failures: dict[str, ScrapeResult] | None = None,
    conflicts: ResultConflictReport | None = None,
) -> None:
    items = tuple(WorkItem(item_id=str(index)) for index in range(1, 4))
    monkeypatch.setattr(
        recovery,
        "_read_immutable_input",
        lambda s3, config, run_id: (
            items,
            "a" * 64,
            '"etag"',
            "version-1",
            True,
            None,
            None,
        ),
    )

    def require_conflicts(s3, config, run_id):
        report = conflicts or _empty_conflicts()
        if report.unresolved_count or report.invalid_resolution_count:
            raise aggregate.RunResultConflictError("blocking conflict evidence")
        return report

    monkeypatch.setattr(aggregate, "require_no_result_conflicts", require_conflicts)
    monkeypatch.setattr(recovery, "_read_failure_conflicts", lambda *args: ())
    monkeypatch.setattr(terminal_journal, "read_terminal_candidates", lambda *args: ())
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidate_resolutions",
        lambda *args: (),
    )
    monkeypatch.setattr(terminal_journal, "read_terminal_decisions", lambda *args: ())
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_decision_conflicts",
        lambda *args: (),
    )
    monkeypatch.setattr(
        aggregate,
        "aggregate_results",
        lambda s3, config, run_id=None: (
            results if results is not None else {"1": _result("1", ScrapeStatus.SUCCESS)}
        ),
    )
    monkeypatch.setattr(
        aggregate,
        "aggregate_failures",
        lambda s3, config, run_id: (
            failures if failures is not None else {"2": _result("2", ScrapeStatus.INVALID_INPUT)}
        ),
    )


def test_inventory_reuses_exact_results_and_failures_and_selects_only_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inventory_sources(monkeypatch)

    inventory = inventory_run(MagicMock(), _config(), "run-1")

    assert inventory.result_ids == {"1"}
    assert inventory.failure_ids == {"2"}
    assert inventory.completed_ids == {"1", "2"}
    assert inventory.missing_ids == ("3",)
    assert [item.item_id for item in inventory.missing_items] == ["3"]


def test_inventory_rejects_unresolved_conflict_before_counting_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = MagicMock()
    _patch_inventory_sources(
        monkeypatch,
        results=results,
        conflicts=_empty_conflicts(unresolved=1),
    )

    with pytest.raises(RecoveryInvariantError, match="blocking result-conflict evidence"):
        inventory_run(MagicMock(), _config(), "run-1")

    results.assert_not_called()


def test_inventory_rejects_invalid_or_orphan_conflict_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inventory_sources(
        monkeypatch,
        conflicts=_empty_conflicts(invalid_resolutions=1),
    )

    with pytest.raises(RecoveryInvariantError, match="blocking result-conflict evidence"):
        inventory_run(MagicMock(), _config(), "run-1")


def test_inventory_rejects_failure_conflict_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inventory_sources(monkeypatch)
    monkeypatch.setattr(
        recovery,
        "_read_failure_conflicts",
        lambda *args: (
            recovery._FailureConflictEvidence(
                key="scraper/runs/run-1/failure-conflicts/v1/1/candidate.json",
                item_id="1",
                candidate_sha256="a" * 64,
                body_sha256="b" * 64,
            ),
        ),
    )

    with pytest.raises(RecoveryInvariantError, match="unresolved failure-conflict"):
        inventory_run(MagicMock(), _config(), "run-1")


def test_failure_conflict_audit_rejects_forged_canonical_observation() -> None:
    canonical = _result("1", ScrapeStatus.FAILED)
    canonical.classification = "canonical"
    candidate = _result("1", ScrapeStatus.INVALID_INPUT)
    candidate.classification = "candidate"

    def failure_body(result: ScrapeResult, hour: int) -> bytes:
        record = result.model_dump(mode="json")
        record["failed_at"] = datetime(2026, 8, 20, hour, tzinfo=UTC).isoformat()
        return json.dumps(record, sort_keys=True).encode()

    canonical_body = failure_body(canonical, 1)
    candidate_body = failure_body(candidate, 2)
    candidate_sha256 = hashlib.sha256(candidate_body).hexdigest()
    conflict_key = f"scraper/runs/run-1/failure-conflicts/v1/1/{candidate_sha256}.json"
    conflict_body = json.dumps(
        {
            "schema_version": 1,
            "terminal_status": "failure-conflict",
            "run_id": "run-1",
            "item_id": "1",
            "detected_at": datetime(2026, 8, 20, 3, tzinfo=UTC).isoformat(),
            "reason": "exact-run permanent failures disagree",
            "canonical_failure_key": "scraper/runs/run-1/failures/1.json",
            "existing_sha256": hashlib.sha256(canonical_body).hexdigest(),
            "candidate_sha256": candidate_sha256,
            "existing_observation": {"forged": True},
            "candidate_observation": semantic_observation(candidate),
            "candidate_body_base64": base64.b64encode(candidate_body).decode(),
        },
        sort_keys=True,
    ).encode()
    s3 = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [{"Contents": [{"Key": conflict_key}]}]
    s3.get_paginator.return_value = paginator
    s3.get_object.side_effect = lambda *, Bucket, Key: {
        "Body": BytesIO(
            canonical_body if Key == "scraper/runs/run-1/failures/1.json" else conflict_body
        )
    }

    with pytest.raises(RecoveryInvariantError, match="canonical evidence is invalid"):
        recovery._read_failure_conflicts(s3, _config(), "run-1")


def test_exact_accept_decision_review_resolves_matching_failure_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _result("1", ScrapeStatus.FAILED)
    canonical.classification = "canonical"
    rejected_result = _result("1", ScrapeStatus.INVALID_INPUT)
    rejected_result.classification = "rejected"
    candidate = _candidate(rejected_result, kind="failure")
    conflict_key = f"scraper/runs/run-1/failure-conflicts/v1/1/{candidate.candidate_sha256}.json"
    _patch_inventory_sources(
        monkeypatch,
        results={},
        failures={"1": canonical},
    )
    monkeypatch.setattr(
        recovery,
        "_read_failure_conflicts",
        lambda *args: (
            recovery._FailureConflictEvidence(
                key=conflict_key,
                item_id="1",
                candidate_sha256=candidate.candidate_sha256,
                body_sha256="b" * 64,
            ),
        ),
    )
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidates",
        lambda *args: (candidate,),
    )
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidate_resolutions",
        lambda *args: (
            TerminalCandidateResolution(
                key="resolution-1",
                body_sha256="1" * 64,
                run_id="run-1",
                item_id="1",
                decision_key="decision-1",
                decision_sha256="2" * 64,
                decision_kind="failure",
                decision_candidate_sha256="3" * 64,
                canonical_key="scraper/runs/run-1/failures/1.json",
                canonical_sha256="3" * 64,
                candidate_key=candidate.key,
                candidate_kind="failure",
                candidate_sha256=candidate.candidate_sha256,
            ),
        ),
    )

    inventory = inventory_run(MagicMock(), _config(), "run-1")

    assert inventory.failure_ids == {"1"}


def test_inventory_rejects_result_failure_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_inventory_sources(
        monkeypatch,
        results={"1": _result("1", ScrapeStatus.SUCCESS)},
        failures={"1": _result("1", ScrapeStatus.FAILED)},
    )

    with pytest.raises(RecoveryInvariantError, match="overlapping"):
        inventory_run(MagicMock(), _config(), "run-1")


def test_inventory_rejects_terminal_id_absent_from_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inventory_sources(
        monkeypatch,
        results={"extra": _result("extra", ScrapeStatus.SUCCESS)},
        failures={},
    )

    with pytest.raises(RecoveryInvariantError, match="absent from immutable input"):
        inventory_run(MagicMock(), _config(), "run-1")


def test_inventory_rejects_nonterminal_status_under_result_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inventory_sources(
        monkeypatch,
        results={"1": _result("1", ScrapeStatus.FAILED)},
        failures={},
    )

    with pytest.raises(RecoveryInvariantError, match="non-conclusive"):
        inventory_run(MagicMock(), _config(), "run-1")


def test_inventory_accepts_semantically_matching_terminal_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inventory_sources(monkeypatch)
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidates",
        lambda *args: (_candidate(_result("1", ScrapeStatus.SUCCESS)),),
    )

    inventory = inventory_run(MagicMock(), _config(), "run-1")

    assert inventory.candidate_count == 1


def test_inventory_blocks_candidate_that_disagrees_with_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _result("1", ScrapeStatus.SUCCESS)
    canonical.data = {"cases": ["A"]}
    candidate = _result("1", ScrapeStatus.SUCCESS)
    candidate.data = {"cases": ["B"]}
    _patch_inventory_sources(monkeypatch, results={"1": canonical}, failures={})
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidates",
        lambda *args: (_candidate(candidate),),
    )

    with pytest.raises(RecoveryInvariantError, match="disagree with canonical"):
        inventory_run(MagicMock(), _config(), "run-1")


def test_inventory_accepts_disagreeing_candidate_with_exact_reviewed_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _result("1", ScrapeStatus.SUCCESS)
    canonical.data = {"cases": ["A"]}
    candidate_result = _result("1", ScrapeStatus.SUCCESS)
    candidate_result.data = {"cases": ["B"]}
    candidate = _candidate(candidate_result)
    conflict_key = f"scraper/runs/run-1/result-conflicts/v2/1/{candidate.candidate_sha256}.json"
    _patch_inventory_sources(
        monkeypatch,
        results={"1": canonical},
        failures={},
        conflicts=_empty_conflicts(resolved_keys=(conflict_key,)),
    )
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidates",
        lambda *args: (candidate,),
    )

    inventory = inventory_run(MagicMock(), _config(), "run-1")

    assert inventory.resolved_conflict_count == 1


def test_inventory_rejects_review_for_a_different_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _result("1", ScrapeStatus.SUCCESS)
    canonical.data = {"cases": ["A"]}
    candidate_result = _result("1", ScrapeStatus.SUCCESS)
    candidate_result.data = {"cases": ["B"]}
    candidate = _candidate(candidate_result)
    wrong_key = "scraper/runs/run-1/result-conflicts/v2/1/" + "a" * 64 + ".json"
    _patch_inventory_sources(
        monkeypatch,
        results={"1": canonical},
        failures={},
        conflicts=_empty_conflicts(resolved_keys=(wrong_key,)),
    )
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidates",
        lambda *args: (candidate,),
    )

    with pytest.raises(RecoveryInvariantError, match="disagree with canonical"):
        inventory_run(MagicMock(), _config(), "run-1")


def test_inventory_blocks_result_candidate_against_failure_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inventory_sources(
        monkeypatch,
        results={},
        failures={"1": _result("1", ScrapeStatus.FAILED)},
    )
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidates",
        lambda *args: (_candidate(_result("1", ScrapeStatus.SUCCESS)),),
    )

    with pytest.raises(RecoveryInvariantError, match="disagree with canonical"):
        inventory_run(MagicMock(), _config(), "run-1")


def test_machine_cross_kind_conflict_does_not_adjudicate_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate(_result("1", ScrapeStatus.SUCCESS))
    _patch_inventory_sources(
        monkeypatch,
        results={},
        failures={"1": _result("1", ScrapeStatus.FAILED)},
    )
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidates",
        lambda *args: (candidate,),
    )
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_decision_conflicts",
        lambda *args: (
            TerminalDecisionConflict(
                key="decision-conflict-1",
                run_id="run-1",
                item_id="1",
                decision_key="decision-1",
                decision_kind="failure",
                decision_candidate_sha256="a" * 64,
                candidate_kind="result",
                candidate_key=candidate.key,
                candidate_sha256=candidate.candidate_sha256,
            ),
        ),
    )

    with pytest.raises(RecoveryInvariantError, match="disagree with canonical"):
        inventory_run(MagicMock(), _config(), "run-1")


def test_explicit_accept_decision_review_resolves_exact_cross_kind_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate(_result("1", ScrapeStatus.SUCCESS))
    _patch_inventory_sources(
        monkeypatch,
        results={},
        failures={"1": _result("1", ScrapeStatus.FAILED)},
    )
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidates",
        lambda *args: (candidate,),
    )
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidate_resolutions",
        lambda *args: (
            TerminalCandidateResolution(
                key="resolution-1",
                body_sha256="1" * 64,
                run_id="run-1",
                item_id="1",
                decision_key="decision-1",
                decision_sha256="2" * 64,
                decision_kind="failure",
                decision_candidate_sha256="3" * 64,
                canonical_key="scraper/runs/run-1/failures/1.json",
                canonical_sha256="3" * 64,
                candidate_key=candidate.key,
                candidate_kind="result",
                candidate_sha256=candidate.candidate_sha256,
            ),
        ),
    )

    inventory = inventory_run(MagicMock(), _config(), "run-1")

    assert inventory.candidate_count == 1


def test_explicit_accept_decision_review_resolves_same_kind_orphan_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _result("1", ScrapeStatus.SUCCESS)
    canonical.data = {"cases": ["canonical"]}
    rejected_result = _result("1", ScrapeStatus.SUCCESS)
    rejected_result.data = {"cases": ["orphan"]}
    candidate = _candidate(rejected_result)
    _patch_inventory_sources(
        monkeypatch,
        results={"1": canonical},
        failures={},
    )
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidates",
        lambda *args: (candidate,),
    )
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidate_resolutions",
        lambda *args: (
            TerminalCandidateResolution(
                key="resolution-1",
                body_sha256="1" * 64,
                run_id="run-1",
                item_id="1",
                decision_key="decision-1",
                decision_sha256="2" * 64,
                decision_kind="result",
                decision_candidate_sha256="3" * 64,
                canonical_key="scraper/runs/run-1/results/1.json",
                canonical_sha256="3" * 64,
                candidate_key=candidate.key,
                candidate_kind="result",
                candidate_sha256=candidate.candidate_sha256,
            ),
        ),
    )

    inventory = inventory_run(MagicMock(), _config(), "run-1")

    assert inventory.candidate_count == 1


def test_each_disagreeing_candidate_requires_its_own_exact_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _result("1", ScrapeStatus.SUCCESS)
    canonical.data = {"cases": ["canonical"]}
    first_result = _result("1", ScrapeStatus.SUCCESS)
    first_result.data = {"cases": ["first"]}
    second_result = _result("1", ScrapeStatus.SUCCESS)
    second_result.data = {"cases": ["second"]}
    first = _candidate(first_result, digest_character="a")
    second = _candidate(second_result, digest_character="b")
    _patch_inventory_sources(
        monkeypatch,
        results={"1": canonical},
        failures={},
    )
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidates",
        lambda *args: (first, second),
    )
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidate_resolutions",
        lambda *args: (
            TerminalCandidateResolution(
                key="resolution-1",
                body_sha256="1" * 64,
                run_id="run-1",
                item_id="1",
                decision_key="decision-1",
                decision_sha256="2" * 64,
                decision_kind="result",
                decision_candidate_sha256="3" * 64,
                canonical_key="scraper/runs/run-1/results/1.json",
                canonical_sha256="3" * 64,
                candidate_key=first.key,
                candidate_kind="result",
                candidate_sha256=first.candidate_sha256,
            ),
        ),
    )

    with pytest.raises(RecoveryInvariantError, match="disagree with canonical"):
        inventory_run(MagicMock(), _config(), "run-1")


def test_inventory_blocks_invalid_terminal_candidate_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inventory_sources(monkeypatch)
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidate_resolutions",
        MagicMock(side_effect=CandidateJournalError("tampered review")),
    )

    with pytest.raises(RecoveryInvariantError, match="invalid terminal-candidate"):
        inventory_run(MagicMock(), _config(), "run-1")


def test_inventory_blocks_malformed_terminal_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inventory_sources(monkeypatch)
    monkeypatch.setattr(
        terminal_journal,
        "read_terminal_candidates",
        MagicMock(side_effect=CandidateJournalError("bad candidate")),
    )

    with pytest.raises(RecoveryInvariantError, match="invalid terminal-candidate"):
        inventory_run(MagicMock(), _config(), "run-1")


def _inventory(
    *,
    missing: tuple[str, ...] = ("3",),
    completed_at: datetime | None = None,
) -> RecoveryInventory:
    items = tuple(WorkItem(item_id=str(index)) for index in range(1, 4))
    completed = {item.item_id for item in items} - set(missing)
    return RecoveryInventory(
        run_id="run-1",
        items=items,
        input_sha256="a" * 64,
        input_etag='"etag"',
        input_version_id="version-1",
        force_rescrape=True,
        terminal_candidate_journal_schema_version=None,
        manifest_completed_at=completed_at,
        result_ids=frozenset(completed),
        failure_ids=frozenset(),
        missing_ids=missing,
        terminal_evidence_sha256="b" * 64,
        candidate_count=0,
        candidate_evidence_sha256="d" * 64,
        conflict_policy_version=1,
        conflict_evidence_sha256="c" * 64,
        resolved_conflict_count=0,
        invalid_resolution_count=0,
    )


@pytest.mark.parametrize(
    ("missing", "queue", "expected"),
    [
        ((), QueueState(0, 0, 0), RecoveryAction.COMPLETE),
        (("3",), QueueState(1, 0, 0), RecoveryAction.LAUNCH_EXISTING_QUEUE),
        (("3",), QueueState(0, 0, 0), RecoveryAction.SEED_MISSING),
    ],
)
def test_plan_selects_one_safe_recovery_action(
    monkeypatch: pytest.MonkeyPatch,
    missing: tuple[str, ...],
    queue: QueueState,
    expected: RecoveryAction,
) -> None:
    check_tasks = MagicMock()
    monkeypatch.setattr(recovery, "inventory_run", lambda *args: _inventory(missing=missing))
    monkeypatch.setattr(recovery, "read_prior_task_arns", lambda *args: ("arn:task/1",))
    monkeypatch.setattr(recovery, "require_prior_tasks_stopped", check_tasks)
    monkeypatch.setattr(recovery, "_require_no_live_started_by_set", lambda *args: None)
    monkeypatch.setattr(recovery, "require_stable_queue_state", lambda *args: queue)

    plan = build_recovery_plan(
        MagicMock(),
        MagicMock(),
        MagicMock(),
        _submitter_config(),
        "run-1",
        attempt_id="attempt-1",
        now=datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert plan.action is expected
    assert plan.attempt_id == "attempt-1"
    check_tasks.assert_called_once()


def test_plan_drains_nonempty_duplicate_queue_after_exact_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recovery, "inventory_run", lambda *args: _inventory(missing=()))
    monkeypatch.setattr(recovery, "read_prior_task_arns", lambda *args: ("arn:task/1",))
    monkeypatch.setattr(recovery, "require_prior_tasks_stopped", lambda *args: None)
    monkeypatch.setattr(recovery, "_require_no_live_started_by_set", lambda *args: None)
    monkeypatch.setattr(
        recovery,
        "require_stable_queue_state",
        lambda *args: QueueState(1, 0, 0),
    )

    plan = build_recovery_plan(
        MagicMock(),
        MagicMock(),
        MagicMock(),
        _submitter_config(),
        "run-1",
    )

    assert plan.action is RecoveryAction.LAUNCH_EXISTING_QUEUE


def test_plan_refuses_nonempty_queue_after_manifest_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery,
        "inventory_run",
        lambda *args: _inventory(
            missing=(),
            completed_at=datetime(2026, 8, 20, tzinfo=UTC),
        ),
    )
    monkeypatch.setattr(recovery, "read_prior_task_arns", lambda *args: ("arn:task/1",))
    monkeypatch.setattr(recovery, "require_prior_tasks_stopped", lambda *args: None)
    monkeypatch.setattr(recovery, "_require_no_live_started_by_set", lambda *args: None)
    monkeypatch.setattr(
        recovery,
        "require_stable_queue_state",
        lambda *args: QueueState(1, 0, 0),
    )

    with pytest.raises(RecoveryInvariantError, match="cannot safely re-enter"):
        build_recovery_plan(
            MagicMock(),
            MagicMock(),
            MagicMock(),
            _submitter_config(),
            "run-1",
        )


def test_prior_task_preflight_rejects_live_or_omitted_tasks() -> None:
    ecs = MagicMock()
    ecs.describe_tasks.return_value = {
        "failures": [],
        "tasks": [{"taskArn": "arn:task/1", "lastStatus": "RUNNING"}],
    }

    with pytest.raises(RecoveryInvariantError, match="prior worker task.*live"):
        require_prior_tasks_stopped(ecs, _submitter_config(), ("arn:task/1",))

    ecs.describe_tasks.return_value = {"failures": [], "tasks": []}
    with pytest.raises(RecoveryInvariantError, match="omitted"):
        require_prior_tasks_stopped(ecs, _submitter_config(), ("arn:task/1",))


def test_prior_task_evidence_allows_definitive_zero_task_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import orchestrate

    s3 = MagicMock()
    stream = MagicMock()
    stream.read.return_value = json.dumps(
        {
            "run_id": "run-1",
            "recorded_at": "2026-08-20T19:00:00+00:00",
            "phase": "queue-seeded",
            "task_arns": [],
        }
    ).encode()
    s3.get_object.return_value = {"Body": stream}
    monkeypatch.setattr(
        orchestrate,
        "get_task_arns",
        lambda *args: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )
    monkeypatch.setattr(recovery, "_task_record_keys", lambda *args: [])

    assert read_prior_task_arns(s3, _config(), "run-1") == ()


def test_plan_resolves_ambiguous_zero_task_launch_by_started_by_quiet_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
    monkeypatch.setattr(recovery, "inventory_run", lambda *args: _inventory())
    monkeypatch.setattr(
        recovery,
        "read_prior_task_arns",
        lambda *args: (_ for _ in ()).throw(
            recovery._AmbiguousInitialLaunch(now - timedelta(minutes=2), ())
        ),
    )
    discover = MagicMock()
    monkeypatch.setattr(recovery, "_require_no_live_started_by_set", discover)
    monkeypatch.setattr(
        recovery,
        "require_stable_queue_state",
        lambda *args: QueueState(0, 0, 0),
    )

    plan = build_recovery_plan(
        MagicMock(),
        MagicMock(),
        MagicMock(),
        _submitter_config(),
        "run-1",
        now=now,
    )

    assert len(plan.prior_task_discovery) == 2
    assert plan.prior_task_discovery[0].startswith("gv-worker-")
    assert plan.prior_task_discovery[1].startswith("gv-monitor-")
    discover.assert_called_once()


def test_queue_preflight_requires_stable_complete_counts_and_no_inflight() -> None:
    sqs = MagicMock()
    sqs.get_queue_attributes.side_effect = [
        {
            "Attributes": {
                "ApproximateNumberOfMessages": "1",
                "ApproximateNumberOfMessagesNotVisible": "0",
                "ApproximateNumberOfMessagesDelayed": "0",
            }
        },
        {
            "Attributes": {
                "ApproximateNumberOfMessages": "0",
                "ApproximateNumberOfMessagesNotVisible": "0",
                "ApproximateNumberOfMessagesDelayed": "0",
            }
        },
    ]
    with pytest.raises(RecoveryInvariantError, match="changed"):
        require_stable_queue_state(sqs, _config(), settle_seconds=0)

    sqs.get_queue_attributes.side_effect = None
    sqs.get_queue_attributes.return_value = {
        "Attributes": {
            "ApproximateNumberOfMessages": "0",
            "ApproximateNumberOfMessagesNotVisible": "1",
            "ApproximateNumberOfMessagesDelayed": "0",
        }
    }
    with pytest.raises(RecoveryInvariantError, match="in-flight"):
        require_stable_queue_state(sqs, _config(), settle_seconds=0)


def _plan(
    action: RecoveryAction = RecoveryAction.SEED_MISSING,
    *,
    queue: QueueState | None = None,
) -> RecoveryPlan:
    return RecoveryPlan(
        run_id="run-1",
        attempt_id="attempt-1",
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
        action=action,
        inventory=_inventory(),
        queue=queue or QueueState(0, 0, 0),
        prior_task_arns=("arn:task/old",),
    )


def test_plan_and_task_evidence_are_append_only(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = MagicMock()
    monkeypatch.setattr(recovery, "verify_plan_is_current", lambda *args: _inventory())
    plan = _plan()

    plan_key = write_recovery_plan(s3, _config(), plan)
    task_key = write_recovery_tasks(s3, _config(), plan, ["arn:task/new"])

    assert plan_key.endswith("/recovery-attempts/attempt-1/plan.json")
    assert task_key.endswith("/recovery-attempts/attempt-1/tasks.json")
    assert all(call.kwargs["IfNoneMatch"] == "*" for call in s3.put_object.call_args_list)
    task_record = json.loads(s3.put_object.call_args.kwargs["Body"])
    assert task_record["attempt_id"] == "attempt-1"
    assert task_record["task_arns"] == ["arn:task/new"]


@pytest.mark.parametrize(
    ("action", "queue_state", "expected_seed_calls"),
    [
        (RecoveryAction.SEED_MISSING, QueueState(0, 0, 0), 1),
        (RecoveryAction.LAUNCH_EXISTING_QUEUE, QueueState(1, 0, 0), 0),
    ],
)
def test_execute_recovery_never_reseeds_completed_or_existing_queue_work(
    monkeypatch: pytest.MonkeyPatch,
    action: RecoveryAction,
    queue_state: QueueState,
    expected_seed_calls: int,
) -> None:
    from aws_batch_scraper import lease, orchestrate, queue

    plan = _plan(action, queue=queue_state)
    monkeypatch.setattr(recovery, "verify_plan_is_current", lambda *args: plan.inventory)
    monkeypatch.setattr(recovery, "require_prior_tasks_stopped", lambda *args: None)
    monkeypatch.setattr(
        recovery,
        "require_stable_queue_state",
        lambda *args: queue_state,
    )
    monkeypatch.setattr(recovery, "write_recovery_plan", MagicMock())
    write_tasks = MagicMock()
    monkeypatch.setattr(recovery, "write_recovery_tasks", write_tasks)
    write_monitor = MagicMock()
    monkeypatch.setattr(recovery, "write_recovery_monitor_task", write_monitor)

    claim = MagicMock()
    monkeypatch.setattr(lease, "claim_run_lease_for_recovery", claim)
    monkeypatch.setattr(lease, "release_run_lease", MagicMock())
    seed = MagicMock(return_value=1)
    monkeypatch.setattr(queue, "seed_queue", seed)
    monkeypatch.setattr(orchestrate, "resolve_split_task_definitions", MagicMock())
    launch_workers = MagicMock(return_value=["arn:task/new"])
    launch_monitor = MagicMock(return_value="arn:task/monitor")
    monkeypatch.setattr(orchestrate, "launch_workers", launch_workers)
    monkeypatch.setattr(orchestrate, "launch_monitor", launch_monitor)

    task_arns = execute_recovery_plan(
        MagicMock(),
        MagicMock(),
        MagicMock(),
        _submitter_config(),
        plan,
        worker_count=2,
        monitor_command=["test-etl", "resume-monitor"],
    )

    assert task_arns == ["arn:task/new"]
    assert seed.call_count == expected_seed_calls
    if expected_seed_calls:
        seeded_items = seed.call_args.args[2]
        assert [item.item_id for item in seeded_items] == ["3"]
        assert not ({item.item_id for item in seeded_items} & plan.inventory.completed_ids)
        assert seed.call_args.kwargs["force_rescrape"] is True
    claim.assert_called_once_with(
        ANY,
        ANY,
        "run-1",
        "attempt-1",
    )
    assert launch_workers.call_args.kwargs["recovery_attempt_id"] == "attempt-1"
    assert launch_workers.call_args.kwargs["force_rescrape"] is True
    assert launch_monitor.call_args.kwargs["recovery_attempt_id"] == "attempt-1"
    write_tasks.assert_called_once()
    write_monitor.assert_called_once()


def test_execute_rejects_queue_change_before_first_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    monkeypatch.setattr(recovery, "verify_plan_is_current", lambda *args: plan.inventory)
    monkeypatch.setattr(recovery, "require_prior_tasks_stopped", lambda *args: None)
    monkeypatch.setattr(
        recovery,
        "require_stable_queue_state",
        lambda *args: QueueState(1, 0, 0),
    )
    write_plan = MagicMock()
    monkeypatch.setattr(recovery, "write_recovery_plan", write_plan)

    with pytest.raises(RecoveryInvariantError, match="changed after recovery planning"):
        execute_recovery_plan(
            MagicMock(),
            MagicMock(),
            MagicMock(),
            _submitter_config(),
            plan,
            monitor_command=["monitor"],
        )

    write_plan.assert_not_called()


@pytest.mark.parametrize("delayed", [0, 2])
def test_definitive_zero_launch_returns_fence_to_same_run(
    monkeypatch: pytest.MonkeyPatch,
    delayed: int,
) -> None:
    from aws_batch_scraper import lease, orchestrate
    from aws_batch_scraper.orchestrate import WorkerLaunchError

    queue_state = QueueState(1, 0, delayed)
    plan = _plan(RecoveryAction.LAUNCH_EXISTING_QUEUE, queue=queue_state)
    monkeypatch.setattr(recovery, "verify_plan_is_current", lambda *args: plan.inventory)
    monkeypatch.setattr(recovery, "require_prior_tasks_stopped", lambda *args: None)
    monkeypatch.setattr(recovery, "require_stable_queue_state", lambda *args: queue_state)
    monkeypatch.setattr(recovery, "write_recovery_plan", MagicMock())
    monkeypatch.setattr(recovery, "write_recovery_launch_failure", MagicMock())
    monkeypatch.setattr(orchestrate, "resolve_split_task_definitions", MagicMock())
    monkeypatch.setattr(
        orchestrate,
        "launch_workers",
        MagicMock(side_effect=WorkerLaunchError([], 1)),
    )
    claimed = RunLease(
        run_id="run-1",
        owner="recovery:attempt-1",
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
        expires_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    monkeypatch.setattr(lease, "claim_run_lease_for_recovery", MagicMock(return_value=claimed))
    returned = MagicMock()
    monkeypatch.setattr(lease, "return_run_lease_from_recovery", returned)
    released = MagicMock()
    monkeypatch.setattr(lease, "release_run_lease", released)

    with pytest.raises(WorkerLaunchError):
        execute_recovery_plan(
            MagicMock(),
            MagicMock(),
            MagicMock(),
            _submitter_config(),
            plan,
            monitor_command=["monitor"],
        )

    returned.assert_called_once_with(ANY, ANY, "run-1", "attempt-1")
    released.assert_not_called()


def test_seed_failure_returns_fence_to_same_run_without_terminal_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import lease, orchestrate, queue

    plan = _plan(RecoveryAction.SEED_MISSING)
    monkeypatch.setattr(recovery, "verify_plan_is_current", lambda *args: plan.inventory)
    monkeypatch.setattr(recovery, "require_prior_tasks_stopped", lambda *args: None)
    monkeypatch.setattr(
        recovery,
        "require_stable_queue_state",
        lambda *args: QueueState(0, 0, 0),
    )
    monkeypatch.setattr(recovery, "write_recovery_plan", MagicMock())
    monkeypatch.setattr(orchestrate, "resolve_split_task_definitions", MagicMock())
    monkeypatch.setattr(queue, "seed_queue", MagicMock(side_effect=TimeoutError("seed lost")))
    monkeypatch.setattr(lease, "claim_run_lease_for_recovery", MagicMock())
    returned = MagicMock()
    monkeypatch.setattr(lease, "return_run_lease_from_recovery", returned)
    released = MagicMock()
    monkeypatch.setattr(lease, "release_run_lease", released)

    with pytest.raises(TimeoutError, match="seed lost"):
        execute_recovery_plan(
            MagicMock(),
            MagicMock(),
            MagicMock(),
            _submitter_config(),
            plan,
            monitor_command=["monitor"],
        )

    returned.assert_called_once_with(ANY, ANY, "run-1", "attempt-1")
    released.assert_not_called()


def _patch_reconciliation_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    now: datetime,
    live_tasks: tuple[str, ...] = (),
) -> tuple[RunLease, MagicMock]:
    from aws_batch_scraper import lease

    active = RunLease(
        run_id="run-1",
        owner="recovery:attempt-1",
        created_at=now - timedelta(minutes=2),
        expires_at=now + timedelta(hours=1),
    )
    monkeypatch.setattr(
        recovery,
        "_read_recovery_plan_created_at",
        lambda *args: now - timedelta(minutes=2),
    )
    monkeypatch.setattr(
        recovery,
        "read_recovery_attempt_task_arns",
        lambda *args: ("arn:task/known",),
    )
    monkeypatch.setattr(
        recovery,
        "_describe_recovery_tasks",
        lambda *args: [{"taskArn": "arn:task/known", "lastStatus": "STOPPED"}],
    )
    monkeypatch.setattr(
        recovery,
        "_list_tasks_started_by",
        lambda *args: live_tasks,
    )
    monkeypatch.setattr(
        recovery,
        "read_queue_state",
        lambda *args: QueueState(2, 0, 0),
    )
    monkeypatch.setattr(recovery, "inventory_run", lambda *args: _inventory())
    monkeypatch.setattr(lease, "read_run_lease", lambda *args: active)
    handoff = MagicMock(
        return_value=RunLease(
            run_id="run-1",
            owner="run-1",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    monkeypatch.setattr(lease, "reconcile_run_lease_from_recovery", handoff)
    return active, handoff


def test_reconciliation_preview_is_read_only_and_allows_stable_queued_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
    _patch_reconciliation_sources(monkeypatch, now=now)
    s3 = MagicMock()

    result = reconcile_recovery_attempt(
        MagicMock(),
        MagicMock(),
        s3,
        _submitter_config(),
        "run-1",
        "attempt-1",
        now=now,
        minimum_attempt_age_seconds=0,
        quiet_seconds=0,
    )

    assert result.queue == QueueState(2, 0, 0)
    assert result.missing_ids == ("3",)
    s3.put_object.assert_not_called()


def test_reconciliation_execute_records_authorization_and_completed_handback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
    _, handoff = _patch_reconciliation_sources(monkeypatch, now=now)
    s3 = MagicMock()

    reconcile_recovery_attempt(
        MagicMock(),
        MagicMock(),
        s3,
        _submitter_config(),
        "run-1",
        "attempt-1",
        execute=True,
        now=now,
        minimum_attempt_age_seconds=0,
        quiet_seconds=0,
    )

    assert s3.put_object.call_count == 2
    authorization = s3.put_object.call_args_list[0].kwargs
    completion = s3.put_object.call_args_list[1].kwargs
    assert authorization["Key"].endswith("-authorized.json")
    assert json.loads(authorization["Body"])["lease_action"] == "return-authorized"
    assert completion["Key"].endswith("-returned.json")
    completion_body = json.loads(completion["Body"])
    assert completion_body["lease_action"] == "returned-to-run"
    assert completion_body["returned_lease"]["owner"] == "run-1"
    assert authorization["IfNoneMatch"] == completion["IfNoneMatch"] == "*"
    handoff.assert_called_once()
    assert handoff.call_args.args[2:] == ("run-1", "attempt-1")
    assert handoff.call_args.kwargs["expected_created_at"] == now - timedelta(minutes=2)


def test_reconciliation_handoff_failure_leaves_only_truthful_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
    _, handoff = _patch_reconciliation_sources(monkeypatch, now=now)
    handoff.side_effect = TimeoutError("CAS response unknown")
    s3 = MagicMock()

    with pytest.raises(TimeoutError, match="CAS response unknown"):
        reconcile_recovery_attempt(
            MagicMock(),
            MagicMock(),
            s3,
            _submitter_config(),
            "run-1",
            "attempt-1",
            execute=True,
            now=now,
            minimum_attempt_age_seconds=0,
            quiet_seconds=0,
        )

    assert s3.put_object.call_count == 1
    evidence = json.loads(s3.put_object.call_args.kwargs["Body"])
    assert evidence["lease_action"] == "return-authorized"


def test_reconciliation_refuses_discoverable_live_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
    _patch_reconciliation_sources(
        monkeypatch,
        now=now,
        live_tasks=("arn:task/live",),
    )

    with pytest.raises(RecoveryInvariantError, match="discoverable live"):
        reconcile_recovery_attempt(
            MagicMock(),
            MagicMock(),
            MagicMock(),
            _submitter_config(),
            "run-1",
            "attempt-1",
            now=now,
            minimum_attempt_age_seconds=0,
            quiet_seconds=0,
        )


def test_started_by_discovery_includes_desired_stopped_task_still_stopping() -> None:
    ecs = MagicMock()
    ecs.list_tasks.side_effect = [
        {"taskArns": []},
        {"taskArns": ["arn:task/stopping"]},
    ]
    ecs.describe_tasks.return_value = {
        "failures": [],
        "tasks": [
            {
                "taskArn": "arn:task/stopping",
                "startedBy": "gv-worker-identity",
                "lastStatus": "DEACTIVATING",
            }
        ],
    }

    assert recovery._list_tasks_started_by(
        ecs,
        _submitter_config(),
        "gv-worker-identity",
    ) == ("arn:task/stopping",)
