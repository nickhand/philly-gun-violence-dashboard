"""Reliable GitHub Actions workflow-dispatch helper."""

import json
import os
import time
from collections.abc import Callable
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from loguru import logger

from aws_batch_scraper.config import require_github_repository, require_github_workflow_file

MAX_ATTEMPTS = 4
REQUEST_TIMEOUT_SECONDS = 30.0


class WorkflowDispatchError(RuntimeError):
    """A required post-scrape workflow could not be dispatched."""


class WorkflowDispatchRejectedError(WorkflowDispatchError):
    """GitHub definitively rejected or could not configure the dispatch."""


class WorkflowDispatchDeliveryUnknownError(WorkflowDispatchError):
    """The request may have been accepted despite losing a definitive response."""


class HttpResponse(Protocol):
    """Narrow response contract needed by the dispatcher."""

    status: int

    def __enter__(self) -> "HttpResponse": ...

    def __exit__(self, *args: object) -> None: ...


class OpenUrl(Protocol):
    """Injectable HTTP opener with a required timeout."""

    def __call__(self, request: Request, *, timeout: float) -> HttpResponse: ...


def _open_url(request: Request, *, timeout: float) -> HttpResponse:
    """Adapt urllib's broad return type to the dispatcher's narrow protocol."""
    return cast(HttpResponse, urlopen(request, timeout=timeout))


def _configuration(
    token: str | None,
    repository: str | None,
    workflow_file: str | None = None,
) -> tuple[str, str, str]:
    resolved_token = token if token is not None else os.environ.get("GITHUB_DISPATCH_TOKEN", "")
    resolved_repository = (
        repository if repository is not None else os.environ.get("GITHUB_REPOSITORY", "")
    )
    resolved_workflow_file = (
        workflow_file if workflow_file is not None else os.environ.get("GITHUB_WORKFLOW_FILE", "")
    )
    if not resolved_token.strip():
        raise WorkflowDispatchRejectedError("GITHUB_DISPATCH_TOKEN is required")
    try:
        validated_repository = require_github_repository(resolved_repository.strip())
        validated_workflow_file = require_github_workflow_file(resolved_workflow_file.strip())
    except ValueError as exc:
        raise WorkflowDispatchRejectedError(str(exc)) from exc
    return resolved_token, validated_repository, validated_workflow_file


def dispatch_workflow(
    run_id: str,
    *,
    token: str | None = None,
    repository: str | None = None,
    workflow_file: str | None = None,
    enabled: bool = True,
    open_url: OpenUrl = _open_url,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Dispatch a workflow run or raise a terminal, retry-bounded error.

    Production callers use the environment-backed defaults. Local tools and
    tests may opt out only by explicitly passing ``enabled=False``. Because a
    workflow dispatch is not idempotent, only an explicit 429 is retried; a
    transport failure or server error has unknown delivery and stops at once.
    """
    if not enabled:
        logger.info(f"Workflow dispatch explicitly disabled for run {run_id}")
        return
    if not run_id.strip():
        raise WorkflowDispatchRejectedError("run_id must not be blank")
    resolved_token, resolved_repository, resolved_workflow_file = _configuration(
        token,
        repository,
        workflow_file,
    )

    url = (
        f"https://api.github.com/repos/{resolved_repository}/actions/workflows/"
        f"{resolved_workflow_file}/dispatches"
    )
    payload = json.dumps(
        {
            "ref": "main",
            "inputs": {"run_id": run_id},
        },
        separators=(",", ":"),
    ).encode()
    request = Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {resolved_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "aws-batch-scraper-monitor",
        },
        method="POST",
    )

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with open_url(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                if response.status == 204:
                    logger.info(f"Dispatched {resolved_workflow_file} workflow for run {run_id}")
                    return
                if response.status == 429:
                    if attempt == MAX_ATTEMPTS:
                        raise WorkflowDispatchRejectedError(
                            "GitHub workflow dispatch was rate-limited after bounded retries"
                        )
                elif 200 <= response.status < 300 or response.status >= 500:
                    raise WorkflowDispatchDeliveryUnknownError(
                        "GitHub workflow dispatch delivery is unknown; not retrying "
                        f"non-idempotent request after HTTP {response.status}"
                    )
                else:
                    raise WorkflowDispatchRejectedError(
                        f"GitHub workflow dispatch was rejected with HTTP {response.status}"
                    )
        except HTTPError as exc:
            if exc.code == 429:
                if attempt == MAX_ATTEMPTS:
                    raise WorkflowDispatchRejectedError(
                        "GitHub workflow dispatch was rate-limited after bounded retries"
                    ) from exc
            elif exc.code >= 500:
                raise WorkflowDispatchDeliveryUnknownError(
                    "GitHub workflow dispatch delivery is unknown; not retrying "
                    f"non-idempotent request after HTTP {exc.code}"
                ) from exc
            else:
                raise WorkflowDispatchRejectedError(
                    f"GitHub workflow dispatch was rejected with HTTP {exc.code}"
                ) from exc
        except (ConnectionError, TimeoutError, URLError) as exc:
            raise WorkflowDispatchDeliveryUnknownError(
                "GitHub workflow dispatch delivery is unknown after a transport failure; "
                "not retrying non-idempotent request"
            ) from exc

        sleep(float(2 ** (attempt - 1)))

    raise WorkflowDispatchRejectedError("GitHub workflow dispatch exhausted its retry budget")
