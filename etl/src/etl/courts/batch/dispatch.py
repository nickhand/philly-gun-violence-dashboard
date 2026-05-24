"""GitHub workflow dispatch helpers for completed courts scrape runs."""

import json
import os
import urllib.error
import urllib.request

from loguru import logger


def dispatch_process_workflow(run_id: str) -> None:
    """Fire a repository_dispatch event to trigger the courts-process workflow.

    Requires ``GITHUB_DISPATCH_TOKEN`` and ``GITHUB_REPOSITORY`` to be set in the
    process environment. Missing credentials are treated as a no-op so local
    monitoring and development runs do not fail.
    """
    token = os.environ.get("GITHUB_DISPATCH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        missing = [
            name
            for name, value in {
                "GITHUB_DISPATCH_TOKEN": token,
                "GITHUB_REPOSITORY": repo,
            }.items()
            if not value
        ]
        logger.info(
            f"{', '.join(missing)} not set — skipping workflow dispatch"
        )
        return

    url = f"https://api.github.com/repos/{repo}/dispatches"
    payload = json.dumps(
        {
            "event_type": "courts-scrape-complete",
            "client_payload": {"run_id": run_id},
        }
    ).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info(f"Dispatched courts-process workflow for run {run_id} (HTTP {resp.status})")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        logger.warning(
            f"Failed to dispatch courts-process workflow: HTTP {exc.code} {exc.reason}: {body}"
        )
    except Exception as exc:
        logger.warning(f"Failed to dispatch courts-process workflow: {exc}")
