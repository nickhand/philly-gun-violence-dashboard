"""Fail the external success heartbeat when a full court publication is overdue."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.request import urlopen


def check_metadata(metadata: object, *, now: datetime, max_age_days: int = 8) -> str:
    if now.tzinfo is None or max_age_days <= 0:
        raise ValueError("Freshness requires an aware clock and a positive age limit")
    if not isinstance(metadata, dict):
        raise ValueError("Court metadata is missing or malformed")
    run_id = metadata.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", run_id):
        raise ValueError("Court metadata has no valid run ID")
    for key, expected in {
        "publication_contract_version": 2,
        "court_search_semantics_version": 2,
        "result_conflict_policy_version": 1,
        "missing_result_count": 0,
        "extra_result_count": 0,
        "unresolved_result_conflict_count": 0,
        "invalid_result_conflict_resolution_count": 0,
    }.items():
        if type(metadata.get(key)) is not int or metadata[key] != expected:
            raise ValueError(f"Court run {run_id} has invalid {key}")
    if metadata.get("selection_mode") != "full" or metadata.get("coverage_complete") is not True:
        raise ValueError(f"Court run {run_id} is not a coverage-complete full publication")
    if metadata.get("status") not in ("success", "partial"):
        raise ValueError(f"Court run {run_id} has no publishable status")
    updated = metadata.get("last_updated")
    if not isinstance(updated, str):
        raise ValueError(f"Court run {run_id} has no last_updated timestamp")
    published_at = datetime.fromisoformat(updated)
    if published_at.tzinfo is None:
        raise ValueError(f"Court run {run_id} timestamp lacks a timezone")
    age = now - published_at
    summary = (
        f"Court run {run_id}: published {published_at.isoformat()}, "
        f"age {age.total_seconds() / 86400:.2f} days, limit {max_age_days} days"
    )
    if age < timedelta(0) or age > timedelta(days=max_age_days):
        raise ValueError(summary + "; publication is overdue or future-dated")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--max-age-days", type=int, default=8)
    args = parser.parse_args()
    try:
        with urlopen(args.api_base_url.rstrip("/") + "/meta/courts", timeout=30) as response:
            data = response.read(256 * 1024 + 1)
            if len(data) > 256 * 1024:
                raise ValueError("Court metadata exceeded the response size limit")
            message = check_metadata(
                json.loads(data), now=datetime.now(UTC), max_age_days=args.max_age_days
            )
        failed = False
    except (OSError, ValueError) as exc:
        message = str(exc)
        failed = True
    # A remote response must not inject extra Actions commands or Markdown rows.
    message = message.replace("\r", " ").replace("\n", " ")
    print(message)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a") as stream:
            stream.write(f"\nCourts freshness: {'FAILED' if failed else 'OK'}\n\n{message}\n")
    if failed:
        print("::error title=Courts publication is not healthy::" + message.replace("%", "%25"))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
