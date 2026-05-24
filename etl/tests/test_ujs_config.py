"""Tests for courts settings behavior."""

from etl.courts.config import SubmitterConfig


def test_submitter_config_accepts_comma_separated_ecs_lists() -> None:
    """ECS list settings should accept simple comma-separated env-style strings."""
    config = SubmitterConfig(
        _env_file=None,
        s3_bucket="bucket",
        aws_account_id="123456789012",
        ecs_subnet_ids="subnet-a, subnet-b",
        ecs_security_group_ids="sg-a,sg-b",
    )

    assert config.ecs_subnet_ids == ["subnet-a", "subnet-b"]
    assert config.ecs_security_group_ids == ["sg-a", "sg-b"]
