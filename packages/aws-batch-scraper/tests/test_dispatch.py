"""Contract tests for the required post-scrape workflow dispatch."""

import io
import json
from urllib.error import HTTPError, URLError

import pytest
from aws_batch_scraper.dispatch import (
    REQUEST_TIMEOUT_SECONDS,
    WorkflowDispatchDeliveryUnknownError,
    WorkflowDispatchError,
    WorkflowDispatchRejectedError,
    dispatch_workflow,
)

WORKFLOW_FILE = "courts-process.yml"


class Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class SequenceOpener:
    def __init__(self, outcomes: list[Response | Exception]) -> None:
        self.outcomes = outcomes
        self.requests = []

    def __call__(self, request, *, timeout: float):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _http_error(code: int) -> HTTPError:
    return HTTPError(
        "https://api.github.com/test",
        code,
        "failure",
        hdrs=None,
        fp=io.BytesIO(b"failure"),
    )


@pytest.mark.parametrize(
    ("token", "repository", "workflow_file", "message"),
    [
        ("", "owner/repo", WORKFLOW_FILE, "GITHUB_DISPATCH_TOKEN is required"),
        ("token", "", WORKFLOW_FILE, "owner/repository"),
        ("token", "too/many/parts", WORKFLOW_FILE, "owner/repository"),
        ("token", "owner/..", WORKFLOW_FILE, "owner/repository"),
        ("token", "owner/repo", "", "GITHUB_WORKFLOW_FILE"),
        ("token", "owner/repo", "../workflow.yml", "GITHUB_WORKFLOW_FILE"),
    ],
)
def test_missing_or_malformed_configuration_is_terminal(
    token: str,
    repository: str,
    workflow_file: str,
    message: str,
) -> None:
    with pytest.raises(WorkflowDispatchError, match=message):
        dispatch_workflow(
            "run-1",
            token=token,
            repository=repository,
            workflow_file=workflow_file,
        )


def test_local_opt_out_must_be_explicit() -> None:
    opener = SequenceOpener([])

    dispatch_workflow("run-1", enabled=False, open_url=opener)

    assert opener.requests == []


def test_exact_204_dispatches_expected_workflow_input() -> None:
    opener = SequenceOpener([Response(204)])

    dispatch_workflow(
        "run-1",
        token="secret",
        repository="owner/repo",
        workflow_file=WORKFLOW_FILE,
        open_url=opener,
    )

    request, timeout = opener.requests[0]
    assert request.full_url == (
        "https://api.github.com/repos/owner/repo/actions/workflows/courts-process.yml/dispatches"
    )
    assert request.method == "POST"
    assert timeout == REQUEST_TIMEOUT_SECONDS
    assert json.loads(request.data) == {
        "ref": "main",
        "inputs": {"run_id": "run-1"},
    }
    assert request.get_header("Authorization") == "Bearer secret"


def test_non_204_success_is_terminal() -> None:
    opener = SequenceOpener([Response(200)])

    with pytest.raises(WorkflowDispatchDeliveryUnknownError, match="HTTP 200"):
        dispatch_workflow(
            "run-1",
            token="secret",
            repository="owner/repo",
            workflow_file=WORKFLOW_FILE,
            open_url=opener,
        )

    assert len(opener.requests) == 1


def test_retries_only_explicit_429_then_succeeds() -> None:
    opener = SequenceOpener([_http_error(429), Response(204)])
    sleeps: list[float] = []

    dispatch_workflow(
        "run-1",
        token="secret",
        repository="owner/repo",
        workflow_file=WORKFLOW_FILE,
        open_url=opener,
        sleep=sleeps.append,
    )

    assert len(opener.requests) == 2
    assert sleeps == [1.0]


def test_retries_returned_429_then_succeeds() -> None:
    """Injected openers need not translate every HTTP error into an exception."""
    opener = SequenceOpener([Response(429), Response(204)])
    sleeps: list[float] = []

    dispatch_workflow(
        "run-1",
        token="secret",
        repository="owner/repo",
        workflow_file=WORKFLOW_FILE,
        open_url=opener,
        sleep=sleeps.append,
    )

    assert len(opener.requests) == 2
    assert sleeps == [1.0]


def test_auth_error_does_not_retry() -> None:
    opener = SequenceOpener([_http_error(401)])

    with pytest.raises(WorkflowDispatchRejectedError, match="HTTP 401"):
        dispatch_workflow(
            "run-1",
            token="secret",
            repository="owner/repo",
            workflow_file=WORKFLOW_FILE,
            open_url=opener,
        )

    assert len(opener.requests) == 1


def test_network_failure_has_unknown_delivery_without_retry() -> None:
    opener = SequenceOpener([URLError("down")])

    with pytest.raises(WorkflowDispatchDeliveryUnknownError, match="not retrying"):
        dispatch_workflow(
            "run-1",
            token="secret",
            repository="owner/repo",
            workflow_file=WORKFLOW_FILE,
            open_url=opener,
            sleep=lambda _: None,
        )

    assert len(opener.requests) == 1


@pytest.mark.parametrize("outcome", [Response(503), _http_error(503)])
def test_server_failure_has_unknown_delivery_without_retry(outcome: Response | Exception) -> None:
    opener = SequenceOpener([outcome])

    with pytest.raises(WorkflowDispatchDeliveryUnknownError, match="not retrying"):
        dispatch_workflow(
            "run-1",
            token="secret",
            repository="owner/repo",
            workflow_file=WORKFLOW_FILE,
            open_url=opener,
            sleep=lambda _: None,
        )

    assert len(opener.requests) == 1


def test_rate_limit_exhaustion_is_definitive_rejection() -> None:
    opener = SequenceOpener([Response(429) for _ in range(4)])

    with pytest.raises(WorkflowDispatchRejectedError, match="rate-limited"):
        dispatch_workflow(
            "run-1",
            token="secret",
            repository="owner/repo",
            workflow_file=WORKFLOW_FILE,
            open_url=opener,
            sleep=lambda _: None,
        )

    assert len(opener.requests) == 4
