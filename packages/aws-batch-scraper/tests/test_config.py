"""Tests for immutable AWS runtime identifiers."""

import pytest
from aws_batch_scraper.config import (
    SubmitterConfig,
    require_exact_ecr_image_uri,
    require_exact_fargate_platform,
    require_exact_iam_role_arn,
    require_exact_secret_arn,
    require_exact_task_definition,
    require_github_repository,
    require_github_workflow_file,
    require_split_task_definitions,
)
from pydantic import ValidationError


@pytest.mark.parametrize(
    "value",
    [
        "ujs-scraper:42",
        "arn:aws:ecs:us-east-1:123456789012:task-definition/ujs-scraper:42",
        "arn:aws-us-gov:ecs:us-gov-west-1:123456789012:task-definition/scraper:1",
    ],
)
def test_exact_task_definition_identifiers_are_accepted(value: str) -> None:
    assert require_exact_task_definition(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "ujs-scraper",
        "ujs-scraper:latest",
        "ujs-scraper:0",
        "ujs-scraper:1:2",
        "arn:aws:ecs:us-east-1:123456789012:task-definition/ujs-scraper",
    ],
)
def test_mutable_or_malformed_task_definition_identifiers_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="exact family:revision"):
        require_exact_task_definition(value)


def test_submitter_config_rejects_bare_task_definition_family() -> None:
    with pytest.raises(ValidationError, match="exact family:revision"):
        SubmitterConfig(
            _env_file=None,
            s3_bucket="bucket",
            s3_scraper_prefix="scraper",
            aws_account_id="123456789012",
            sqs_queue_name="queue",
            sqs_dlq_name="queue-dlq",
            ecs_cluster_name="cluster",
            ecs_task_definition="ujs-scraper",
            ecs_monitor_task_definition="ujs-scraper-monitor:1",
            ecs_container_name="worker",
            ecs_subnet_ids=["subnet-1"],
            ecs_security_group_ids=["sg-1"],
        )


def _submitter_kwargs() -> dict[str, object]:
    return {
        "_env_file": None,
        "s3_bucket": "bucket",
        "s3_scraper_prefix": "scraper",
        "aws_account_id": "123456789012",
        "sqs_queue_name": "queue",
        "sqs_dlq_name": "queue-dlq",
        "ecs_cluster_name": "cluster",
        "ecs_task_definition": "ujs-scraper:42",
        "ecs_monitor_task_definition": "ujs-scraper-monitor:17",
        "ecs_expected_image_uri": (
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper@sha256:" + "a" * 64
        ),
        "ecs_expected_task_role_arn": "arn:aws:iam::123456789012:role/ujs-scraper-task",
        "ecs_expected_execution_role_arn": ("arn:aws:iam::123456789012:role/ujs-scraper-execution"),
        "ecs_expected_monitor_secret_arn": (
            "arn:aws:secretsmanager:us-east-1:123456789012:"
            "secret:ujs-scraper/github-dispatch-token-AbCdEf"
        ),
        "ecs_platform_version": "1.4.0",
        "ecs_container_name": "worker",
        "ecs_subnet_ids": ["subnet-1"],
        "ecs_security_group_ids": ["sg-1"],
    }


def test_exact_ecr_release_image_uri_is_bound_to_account_and_region() -> None:
    value = "123456789012.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper@sha256:" + "a" * 64

    assert (
        require_exact_ecr_image_uri(
            value,
            account_id="123456789012",
            region="us-east-1",
        )
        == value
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        "ujs-scraper:latest",
        "999999999999.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper@sha256:" + "a" * 64,
        "123456789012.dkr.ecr.us-west-2.amazonaws.com/ujs-scraper@sha256:" + "a" * 64,
        "123456789012.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper@sha256:not-a-digest",
    ],
)
def test_ecr_release_image_uri_rejects_wrong_or_mutable_identity(value: str | None) -> None:
    with pytest.raises(ValueError, match="ECS_EXPECTED_IMAGE_URI"):
        require_exact_ecr_image_uri(
            value,
            account_id="123456789012",
            region="us-east-1",
        )


def test_exact_iam_role_arn_is_bound_to_account() -> None:
    value = "arn:aws:iam::123456789012:role/service/ujs-scraper-task"

    assert (
        require_exact_iam_role_arn(
            value,
            account_id="123456789012",
            setting_name="ECS_EXPECTED_TASK_ROLE_ARN",
        )
        == value
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "ujs-scraper-task",
        "arn:aws:iam::999999999999:role/ujs-scraper-task",
        "arn:aws:iam::123456789012:user/ujs-scraper-task",
        "arn:aws:iam::123456789012:role/path//ujs-scraper-task",
    ],
)
def test_iam_role_arn_rejects_wrong_or_ambiguous_identity(value: str | None) -> None:
    with pytest.raises(ValueError, match="exact same-account IAM role ARN"):
        require_exact_iam_role_arn(
            value,
            account_id="123456789012",
            setting_name="ECS_EXPECTED_TASK_ROLE_ARN",
        )


def test_exact_monitor_secret_arn_is_bound_to_account_and_region() -> None:
    value = (
        "arn:aws:secretsmanager:us-east-1:123456789012:"
        "secret:ujs-scraper/github-dispatch-token-AbCdEf"
    )

    assert (
        require_exact_secret_arn(
            value,
            account_id="123456789012",
            region="us-east-1",
            setting_name="ECS_EXPECTED_MONITOR_SECRET_ARN",
        )
        == value
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "ujs-scraper/github-dispatch-token",
        (
            "arn:aws:secretsmanager:us-east-1:999999999999:"
            "secret:ujs-scraper/github-dispatch-token-AbCdEf"
        ),
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:"
            "secret:ujs-scraper/github-dispatch-token-AbCdEf"
        ),
        (
            "arn:aws:secretsmanager:us-east-1:123456789012:"
            "secret:ujs-scraper//github-dispatch-token-AbCdEf"
        ),
    ],
)
def test_monitor_secret_arn_rejects_wrong_or_ambiguous_identity(value: str | None) -> None:
    with pytest.raises(ValueError, match="same-account, same-region Secrets Manager ARN"):
        require_exact_secret_arn(
            value,
            account_id="123456789012",
            region="us-east-1",
            setting_name="ECS_EXPECTED_MONITOR_SECRET_ARN",
        )


def test_submitter_config_rejects_unreviewed_fargate_platform() -> None:
    values = _submitter_kwargs()
    values["ecs_platform_version"] = "LATEST"

    with pytest.raises(ValueError, match="ECS_PLATFORM_VERSION"):
        SubmitterConfig(**values)


@pytest.mark.parametrize("value", ["LATEST", "1.3.0", "1.4", ""])
def test_exact_fargate_platform_rejects_mutable_or_unreviewed_values(value: str) -> None:
    with pytest.raises(ValueError, match="ECS_PLATFORM_VERSION"):
        require_exact_fargate_platform(value)


def test_submitter_config_requires_monitor_task_definition() -> None:
    values = _submitter_kwargs()
    del values["ecs_monitor_task_definition"]

    with pytest.raises(ValidationError, match="ecs_monitor_task_definition"):
        SubmitterConfig(**values)


def test_submitter_config_rejects_bare_monitor_task_definition_family() -> None:
    values = _submitter_kwargs()
    values["ecs_monitor_task_definition"] = "ujs-scraper-monitor"

    with pytest.raises(ValidationError, match="ECS_MONITOR_TASK_DEFINITION"):
        SubmitterConfig(**values)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ecs_subnet_ids", "", "between 1 and 16"),
        ("ecs_subnet_ids", [], "between 1 and 16"),
        ("ecs_subnet_ids", ["subnet-1", "subnet-1"], "unique subnet"),
        ("ecs_subnet_ids", ["not-a-subnet"], "unique subnet"),
        ("ecs_security_group_ids", "", "between 1 and 5"),
        ("ecs_security_group_ids", ["sg-1", "sg-1"], "unique sg-"),
    ],
)
def test_submitter_config_rejects_unsafe_network_lists(
    field: str,
    value: object,
    message: str,
) -> None:
    values = _submitter_kwargs()
    values[field] = value

    with pytest.raises(ValidationError, match=message):
        SubmitterConfig(**values)


@pytest.mark.parametrize(
    ("worker", "monitor"),
    [
        ("ujs-scraper:42", "ujs-scraper:42"),
        (
            "ujs-scraper:42",
            "arn:aws:ecs:us-east-1:123456789012:task-definition/ujs-scraper:42",
        ),
    ],
)
def test_shared_worker_and_monitor_definition_is_rejected(worker: str, monitor: str) -> None:
    with pytest.raises(ValueError, match="different task-definition revisions"):
        require_split_task_definitions(worker, monitor)


def test_submitter_config_rejects_shared_worker_and_monitor_definition() -> None:
    values = _submitter_kwargs()
    values["ecs_monitor_task_definition"] = "ujs-scraper:42"

    with pytest.raises(ValidationError, match="different task-definition revisions"):
        SubmitterConfig(**values)


def test_distinct_worker_and_monitor_definitions_are_accepted() -> None:
    assert require_split_task_definitions("ujs-scraper:42", "ujs-scraper-monitor:17") == (
        "ujs-scraper:42",
        "ujs-scraper-monitor:17",
    )


@pytest.mark.parametrize("value", [None, "", "owner", "/repo", "owner/", "owner/.."])
def test_github_repository_target_is_required_and_structured(value: str | None) -> None:
    with pytest.raises(ValueError, match="owner/repository"):
        require_github_repository(value)


def test_github_repository_target_is_accepted() -> None:
    assert require_github_repository("owner/repository.name") == "owner/repository.name"


@pytest.mark.parametrize("value", [None, "", "workflow", "../workflow.yml", "dir/job.yml"])
def test_github_workflow_target_is_required_and_structured(value: str | None) -> None:
    with pytest.raises(ValueError, match="workflow filename"):
        require_github_workflow_file(value)


@pytest.mark.parametrize("value", ["courts-process.yml", "release_2.yaml"])
def test_github_workflow_target_is_accepted(value: str) -> None:
    assert require_github_workflow_file(value) == value
