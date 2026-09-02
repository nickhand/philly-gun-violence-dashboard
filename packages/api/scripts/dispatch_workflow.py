"""Dispatch one allowlisted GitHub Actions workflow with bounded retries."""

import argparse
import os
import time
from collections.abc import Callable, Sequence
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPOSITORY = "nickhand/philly-gun-violence-dashboard"
ALLOWED_WORKFLOWS = frozenset(
    {
        "chrome-update.yml",
        "courts-scrape.yml",
        "daily-homicide-sync.yml",
        "daily-shootings-sync.yml",
        "frontend-quality.yml",
        "production-smoke.yml",
        "security-quality.yml",
    }
)
MAX_ATTEMPTS = 4
REQUEST_TIMEOUT_SECONDS = 30.0


class WorkflowDispatchError(RuntimeError):
    """A scheduled workflow could not be dispatched conclusively."""


class WorkflowDispatchRejectedError(WorkflowDispatchError):
    """GitHub definitively did not accept the workflow dispatch."""


class WorkflowDispatchDeliveryUnknownError(WorkflowDispatchError):
    """GitHub may have accepted the non-idempotent dispatch request."""


class HttpResponse(Protocol):
    """Minimum response contract used by the dispatcher."""

    status: int

    def __enter__(self) -> "HttpResponse": ...

    def __exit__(self, *args: object) -> None: ...


class OpenUrl(Protocol):
    """Callable HTTP opener with a bounded request timeout."""

    def __call__(self, request: Request, *, timeout: float) -> HttpResponse: ...


def _open_url(request: Request, *, timeout: float) -> HttpResponse:
    """Adapt urllib's broad signature to the dispatcher's narrow contract."""
    return cast(HttpResponse, urlopen(request, timeout=timeout))


def dispatch_workflow(
    workflow: str,
    *,
    token: str,
    open_url: OpenUrl = _open_url,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Dispatch an allowlisted workflow without retrying ambiguous delivery.

    A workflow dispatch is not idempotent. Only GitHub's explicit 429 response
    proves that it did not accept the request, so only that outcome is retried.
    Transport failures and 5xx responses stop immediately with a typed
    delivery-unknown error to avoid starting the same workflow twice.
    """
    if workflow not in ALLOWED_WORKFLOWS:
        raise ValueError(f"Workflow is not allowlisted: {workflow}")
    if not token.strip():
        raise ValueError("GITHUB_PAT must not be blank")

    url = f"https://api.github.com/repos/{REPOSITORY}/actions/workflows/{workflow}/dispatches"
    request = Request(
        url,
        data=b'{"ref":"main"}',
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "philly-gun-violence-dashboard-cron",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with open_url(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                if response.status == 204:
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


def main(argv: Sequence[str] | None = None) -> None:
    """Parse arguments and dispatch one workflow."""
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow", choices=sorted(ALLOWED_WORKFLOWS))
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_PAT", "")
    dispatch_workflow(args.workflow, token=token)


if __name__ == "__main__":
    main()
