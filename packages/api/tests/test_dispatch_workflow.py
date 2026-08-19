"""Tests for reliable scheduled GitHub workflow dispatches."""

from collections.abc import Iterator
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from scripts.dispatch_workflow import (
    WorkflowDispatchDeliveryUnknownError,
    WorkflowDispatchRejectedError,
    dispatch_workflow,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class FakeResponse:
    """Minimal context-managed HTTP response."""

    def __init__(self, status: int = 204) -> None:
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class SequenceOpener:
    """Return or raise a predefined sequence of outcomes."""

    def __init__(self, outcomes: list[FakeResponse | Exception]) -> None:
        self._outcomes: Iterator[FakeResponse | Exception] = iter(outcomes)
        self.calls: list[tuple[Request, float]] = []

    def __call__(self, request: Request, *, timeout: float) -> FakeResponse:
        self.calls.append((request, timeout))
        outcome = next(self._outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _http_error(code: int) -> HTTPError:
    return HTTPError("https://example.test", code, "failure", hdrs=Message(), fp=None)


def test_dispatch_requires_allowlisted_workflow_and_token() -> None:
    """Ambient input cannot select an arbitrary repository endpoint."""
    with pytest.raises(ValueError, match="not allowlisted"):
        dispatch_workflow("other.yml", token="secret")
    with pytest.raises(ValueError, match="must not be blank"):
        dispatch_workflow("daily-shootings-sync.yml", token="  ")


def test_dispatch_validates_success_and_request_contract() -> None:
    """GitHub's documented 204 response is the only successful outcome."""
    opener = SequenceOpener([FakeResponse()])

    dispatch_workflow("daily-shootings-sync.yml", token="secret", open_url=opener)

    assert len(opener.calls) == 1
    request, timeout = opener.calls[0]
    assert timeout == 30.0
    assert request.method == "POST"
    assert request.data == b'{"ref":"main"}'
    assert request.get_header("Authorization") == "Bearer secret"


def test_production_smoke_is_an_allowlisted_external_heartbeat() -> None:
    opener = SequenceOpener([FakeResponse()])

    dispatch_workflow("production-smoke.yml", token="secret", open_url=opener)

    request, _ = opener.calls[0]
    assert request.full_url.endswith("/production-smoke.yml/dispatches")


def test_frontend_quality_remains_allowlisted_for_phase_two() -> None:
    opener = SequenceOpener([FakeResponse()])

    dispatch_workflow("frontend-quality.yml", token="secret", open_url=opener)

    request, _ = opener.calls[0]
    assert request.full_url.endswith("/frontend-quality.yml/dispatches")


def test_dispatch_retries_only_rate_limit_with_bounded_backoff() -> None:
    """An explicit 429 proves non-acceptance and is safe to retry."""
    opener = SequenceOpener([_http_error(429), FakeResponse()])
    sleeps: list[float] = []

    dispatch_workflow(
        "daily-homicide-sync.yml",
        token="secret",
        open_url=opener,
        sleep=sleeps.append,
    )

    assert len(opener.calls) == 2
    assert sleeps == [1.0]


@pytest.mark.parametrize(
    "outcome",
    [ConnectionError("reset"), URLError("offline"), _http_error(503)],
)
def test_dispatch_does_not_retry_ambiguous_failure(outcome: Exception) -> None:
    """A lost response may follow acceptance, so retrying could duplicate a run."""
    opener = SequenceOpener([outcome])
    sleeps: list[float] = []

    with pytest.raises(WorkflowDispatchDeliveryUnknownError, match="not retrying"):
        dispatch_workflow(
            "daily-homicide-sync.yml",
            token="secret",
            open_url=opener,
            sleep=sleeps.append,
        )

    assert len(opener.calls) == 1
    assert sleeps == []


def test_dispatch_treats_unexpected_success_as_unknown_delivery() -> None:
    opener = SequenceOpener([FakeResponse(202)])

    with pytest.raises(WorkflowDispatchDeliveryUnknownError, match="HTTP 202"):
        dispatch_workflow("daily-homicide-sync.yml", token="secret", open_url=opener)

    assert len(opener.calls) == 1


def test_dispatch_fails_immediately_for_authentication_error() -> None:
    """A bad credential is observable rather than silently reported as success."""
    opener = SequenceOpener([_http_error(401)])

    with pytest.raises(WorkflowDispatchRejectedError, match="HTTP 401"):
        dispatch_workflow("courts-scrape.yml", token="expired", open_url=opener)

    assert len(opener.calls) == 1


def test_dispatch_fails_after_rate_limit_retry_budget() -> None:
    """Persistent definitive non-acceptance has a finite terminal outcome."""
    opener = SequenceOpener([_http_error(429) for _ in range(4)])
    sleeps: list[float] = []

    with pytest.raises(WorkflowDispatchRejectedError, match="rate-limited"):
        dispatch_workflow(
            "daily-shootings-sync.yml",
            token="secret",
            open_url=opener,
            sleep=sleeps.append,
        )

    assert len(opener.calls) == 4
    assert sleeps == [1.0, 2.0, 4.0]


def test_frontend_weekly_schedule_stays_native_during_phase_one() -> None:
    """The first scheduler release must not create a weekly-check gap or duplicate owner."""
    workflow = (REPOSITORY_ROOT / ".github/workflows/frontend-quality.yml").read_text()
    crontab = (REPOSITORY_ROOT / "packages/api/crontab").read_text()

    assert 'cron: "30 9 * * 1"' in workflow
    assert "dispatch_workflow.py frontend-quality.yml" not in crontab


def test_scheduler_deploy_contract_prevents_overlapping_cron_machines() -> None:
    scheduler_config = (REPOSITORY_ROOT / "fly.scheduler.toml").read_text()
    recipes = (REPOSITORY_ROOT / "packages/api/just/api.just").read_text()

    assert 'strategy = "immediate"' in scheduler_config
    assert "fly-deploy-scheduler: fly-assert-legacy-scheduler-stopped" in recipes
    assert "--strategy immediate --ha=false" in recipes
    assert "fly-assert-single-scheduler" in recipes
    assert 'flyctl secrets unset GITHUB_PAT --app "{{ fly_api_app }}"' in recipes
