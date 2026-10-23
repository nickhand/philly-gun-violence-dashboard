"""Tests for courts settings behavior."""

import os

import pytest
from pydantic import ValidationError

from etl.courts.config import CourtsSubmitterConfig


def test_submitter_config_accepts_comma_separated_ecs_lists() -> None:
    """ECS list settings should accept simple comma-separated env-style strings."""
    config = CourtsSubmitterConfig(
        _env_file=None,
        s3_bucket="bucket",
        aws_account_id="123456789012",
        ecs_task_definition="ujs-scraper:1",
        ecs_monitor_task_definition="ujs-scraper-monitor:1",
        ecs_subnet_ids="subnet-a, subnet-b",
        ecs_security_group_ids="sg-a,sg-b",
    )

    assert config.ecs_subnet_ids == ["subnet-a", "subnet-b"]
    assert config.ecs_security_group_ids == ["sg-a", "sg-b"]


def test_courts_submitter_keeps_default_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {})
    config = CourtsSubmitterConfig(
        _env_file=None,
        s3_bucket="bucket",
        aws_account_id="123456789012",
        ecs_task_definition="ujs-scraper:1",
        ecs_monitor_task_definition="ujs-scraper-monitor:1",
        ecs_subnet_ids=["subnet-a"],
        ecs_security_group_ids=["sg-a"],
    )

    assert config.github_workflow_file == "courts-process.yml"


def test_courts_submitter_rejects_null_workflow() -> None:
    with pytest.raises(ValidationError, match="GITHUB_WORKFLOW_FILE"):
        CourtsSubmitterConfig(
            _env_file=None,
            s3_bucket="bucket",
            aws_account_id="123456789012",
            ecs_task_definition="ujs-scraper:1",
            ecs_monitor_task_definition="ujs-scraper-monitor:1",
            ecs_subnet_ids=["subnet-a"],
            ecs_security_group_ids=["sg-a"],
            github_workflow_file=None,
        )
