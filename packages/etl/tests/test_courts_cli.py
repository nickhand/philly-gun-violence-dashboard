"""Tests for courts command-line preflight checks."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from aws_batch_scraper import orchestrate

from etl.courts import cli


def test_aws_smoke_probes_only_the_scraper_s3_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The GitHub role has prefix-scoped ListBucket, not bucket-wide access."""
    config = SimpleNamespace(
        s3_bucket="dashboard-bucket",
        s3_scraper_prefix="ujs-scraper",
        sqs_queue_url="https://sqs.us-east-1.amazonaws.com/123456789012/ujs-incidents",
    )
    sqs = MagicMock(spec=["get_queue_attributes"])
    s3 = MagicMock(spec=["list_objects_v2"])
    ecs = MagicMock()
    session = MagicMock()
    session.client.side_effect = {"sqs": sqs, "s3": s3, "ecs": ecs}.__getitem__
    resolve = MagicMock()

    monkeypatch.setattr(cli, "CourtsSubmitterConfig", lambda: config)
    monkeypatch.setattr(cli, "make_boto3_session", lambda *, config: session)
    monkeypatch.setattr(orchestrate, "resolve_split_task_definitions", resolve)

    cli.smoke(skip_portal=True)

    sqs.get_queue_attributes.assert_called_once_with(
        QueueUrl=config.sqs_queue_url,
        AttributeNames=["QueueArn"],
    )
    s3.list_objects_v2.assert_called_once_with(
        Bucket="dashboard-bucket",
        Prefix="ujs-scraper/",
        MaxKeys=1,
    )
    resolve.assert_called_once_with(ecs, config)


def test_successful_nonpublishing_processing_releases_lease_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A validated sample/incremental no-op must not strand the active lease."""
    from aws_batch_scraper import aggregate, lease

    from etl.courts import pipeline

    config = SimpleNamespace(run_id="sample-run")
    s3 = MagicMock()
    session = MagicMock()
    session.client.return_value = s3
    monkeypatch.setattr(cli, "CourtsWorkerConfig", lambda: config)
    monkeypatch.setattr(cli, "make_boto3_session", lambda *, config: session)
    completed_preflight = MagicMock()
    claim = MagicMock()
    release = MagicMock(return_value=True)
    process_results = MagicMock(return_value=None)
    monkeypatch.setattr(aggregate, "read_run_items", completed_preflight)
    monkeypatch.setattr(lease, "claim_run_lease_for_processing", claim)
    monkeypatch.setattr(lease, "release_run_lease", release)
    monkeypatch.setattr(pipeline, "process_results", process_results)

    cli.process()

    completed_preflight.assert_called_once_with(
        s3,
        config,
        "sample-run",
        require_completed=True,
    )
    assert claim.call_args.args[:3] == (s3, config, "sample-run")
    process_results.assert_called_once_with(s3, config)
    assert release.call_args.args[:3] == (s3, config, "sample-run")
    assert release.call_args.kwargs == {
        "owner": claim.call_args.args[3],
        "terminal_status": "success",
    }
