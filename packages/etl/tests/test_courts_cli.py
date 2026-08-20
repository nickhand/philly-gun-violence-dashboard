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
