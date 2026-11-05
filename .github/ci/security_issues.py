"""Reconcile verified scraper findings, weekly maintenance, and overdue scan coverage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path

BOT = "github-actions[bot]"
BOT_ID = 41898282
COVERAGE_LIMIT = timedelta(hours=48)
AUDIT_WORKFLOW = "security-quality.yml"


def github(path, *, method="GET", body=None, pages=False):
    endpoint = f"repos/{os.environ['GITHUB_REPOSITORY']}"
    if path:
        endpoint += f"/{path}"
    command = ["gh", "api", "--method", method, endpoint]
    if pages:
        command.extend(["--paginate", "--slurp"])
    if body is not None:
        command.extend(["--input", "-"])
    result = subprocess.check_output(
        command, input=json.dumps(body) if body is not None else None, text=True
    )
    return json.loads(result)


def run_url():
    server = os.environ["GITHUB_SERVER_URL"]
    repo = os.environ["GITHUB_REPOSITORY"]
    run = os.environ["GITHUB_RUN_ID"]
    return f"{server}/{repo}/actions/runs/{run}/attempts/{os.environ['GITHUB_RUN_ATTEMPT']}"


def single_line(value):
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n`"):
        raise ValueError("Invalid value in deployed scan finding")
    return value


def deployed_reports(observation, now):
    if (
        type(observation.get("schema_version")) is not int
        or observation["schema_version"] != 1
        or not re.fullmatch(r"[0-9a-f]{40}", observation.get("source_sha", ""))
        or not re.fullmatch(r"[\w./:-]+@sha256:[0-9a-f]{64}", observation.get("image", ""))
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", observation.get("image_id", ""))
        or not isinstance(observation.get("findings"), list)
    ):
        raise ValueError("Incomplete deployed image observation")
    observed = datetime.fromisoformat(observation["observed_at"])
    if observed.tzinfo is None or not now - timedelta(hours=2) <= observed <= now:
        raise ValueError("Expired or future deployed image observation")
    packages = defaultdict(set)
    for finding in observation["findings"]:
        package, version, component, advisory, severity = (
            single_line(finding[field])
            for field in ("package", "version", "component", "advisory", "severity")
        )
        fixes = finding["fixed_versions"]
        if (
            component not in {"image", "chrome", "ecr"}
            or severity not in {"Critical", "High", "Unknown"}
            or not isinstance(fixes, list)
        ):
            raise ValueError("Invalid component, severity or fixed versions in deployed scan")
        if component == "ecr":
            completed = datetime.fromisoformat(observation["ecr"]["scan_completed_at"])
            if completed.tzinfo is None or completed > observed:
                raise ValueError("Invalid ECR scan time")
            component = f"ECR scan of {completed.date().isoformat()}"
        fixed = ", ".join(sorted({single_line(v) for v in fixes})) or "no fix listed"
        packages[package].add(
            f"- {severity} `{advisory}` in `{version}` ({component}), fix: `{fixed}`"
        )
    reports = {}
    for package, rows in packages.items():
        details = (
            f"The deployed courts scraper contains affected package `{package}`. "
            "Review the advisories and available fixes. A clean scan of the active image "
            "will close this issue.\n\n"
            f"Image: `{observation['image']}`\n\n"
        )
        ordered = sorted(rows)
        # Leave room under GitHub's issue-body size limit for the evidence link.
        shown = []
        size = len(details)
        for row in ordered:
            if size + len(row) > 60_000:
                break
            shown.append(row)
            size += len(row) + 1
        details += "\n".join(shown)
        if len(shown) < len(ordered):
            details += f"\n\nSee the scan artifact for all {len(ordered)} findings."
        key = hashlib.sha256(package.encode()).hexdigest()
        reports[key] = (f"Deployed scraper security: {package}", details)
    return reports


def weekly_reports(results):
    if not isinstance(results, dict) or not results:
        raise ValueError("Expected weekly audit results by component")
    reports = {}
    for name, status in results.items():
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
            raise ValueError("Invalid weekly check name")
        if status == "success":
            reports[name] = None
        elif status == "failure":
            reports[name] = (
                f"Weekly security maintenance: {name}",
                f"The weekly `{name}` check failed. Inspect the linked run and associated "
                "repair PRs during maintenance. A successful weekly check closes this issue.",
            )
        # A skipped, cancelled, or unknown job has no resolution evidence.
    return reports


def repository_artifacts():
    # Most checks find the latest verified artifact on the first page. Only gaps
    # require a full search, including observations produced by old-run retries.
    for page in count(1):
        artifacts = github(f"actions/artifacts?per_page=100&page={page}")["artifacts"]
        yield from artifacts
        if len(artifacts) < 100:
            return


def coverage_reports(now):
    repo = github("")
    if repo["default_branch"] != "main":
        raise ValueError("Expected protected main as the default branch")
    workflow_id = github(f"actions/workflows/{AUDIT_WORKFLOW}")["id"]
    for artifact in repository_artifacts():
        name = re.fullmatch(
            r"verified-deployed-scraper-([1-9][0-9]*)-([1-9][0-9]*)", artifact["name"]
        )
        if (
            not name
            or artifact["expired"]
            or artifact["size_in_bytes"] <= 0
            or datetime.fromisoformat(artifact["expires_at"]) <= now
        ):
            continue
        created = datetime.fromisoformat(artifact["created_at"])
        if not now - COVERAGE_LIMIT <= created <= now:
            continue
        run_id, attempt = map(int, name.groups())
        origin = artifact.get("workflow_run") or {}
        if (
            origin.get("id") != run_id
            or origin.get("repository_id") != repo["id"]
            or origin.get("head_repository_id") != repo["id"]
            or origin.get("head_branch") != "main"
        ):
            continue
        run = github(f"actions/runs/{run_id}")
        if (
            run["id"] != run_id
            or run["run_attempt"] < attempt
            or run["workflow_id"] != workflow_id
            or run["event"] != "workflow_dispatch"
            or run["repository"]["id"] != repo["id"]
            or (run.get("head_repository") or {}).get("id") != repo["id"]
            or run["head_branch"] != "main"
            or run["head_sha"] != origin["head_sha"]
        ):
            continue
        if run["run_attempt"] != attempt:
            run = github(f"actions/runs/{run_id}/attempts/{attempt}")
            if created > datetime.fromisoformat(run["updated_at"]):
                continue
        if datetime.fromisoformat(run["run_started_at"]) <= created:
            return {"active": None}
    return {
        "active": (
            "Overdue deployed scraper security scan",
            "No verified scan of the deployed scraper was published in the past 48 hours. "
            "Check the scheduler, audit logs, credentials, scanner data, and artifact upload. "
            "A fresh verified observation closes this issue.",
        )
    }


def reconcile(scope, reports, *, close_missing=False):
    pattern = re.compile(rf"<!-- philly-security:v1:{scope}:([a-zA-Z0-9_-]+) -->\n")
    managed = defaultdict(list)
    pages = github("issues?state=all&creator=github-actions%5Bbot%5D&per_page=100", pages=True)
    for page in pages:
        for issue in page:
            author = issue["user"]
            if "pull_request" in issue or author["login"] != BOT or author["id"] != BOT_ID:
                continue
            marker = pattern.match(issue.get("body") or "")
            if marker:
                managed[marker[1]].append(issue)

    active = []
    maintainer = os.environ["SECURITY_MAINTAINER"] if scope in {"deployed", "coverage"} else None
    keys = set(reports) | (set(managed) if close_missing else set())
    for key in sorted(keys):
        report = reports.get(key)
        issues = managed[key]
        open_issues = [issue for issue in issues if issue["state"] == "open"]
        if report is not None:
            title, details = report
            stable = f"<!-- philly-security:v1:{scope}:{key} -->\n{details}"
            body = f"{stable}\n\n[Run evidence]({run_url()})"
            payload = {"title": title, "body": body}
            if not issues:
                if maintainer:
                    payload["assignees"] = [maintainer]
                canonical = github("issues", method="POST", body=payload)
            else:
                canonical = min(open_issues or issues, key=lambda issue: issue["number"])
                if canonical["state"] == "closed":
                    payload["state"] = "open"
                    if maintainer:
                        existing = {user["login"] for user in canonical["assignees"]}
                        payload["assignees"] = sorted(existing | {maintainer})
                if (
                    canonical["state"] != "open"
                    or canonical["title"] != title
                    or canonical["body"].partition("\n\n[Run evidence](")[0] != stable
                ):
                    github(f"issues/{canonical['number']}", method="PATCH", body=payload)
            active.append(canonical["number"])
            open_issues = [issue for issue in open_issues if issue["number"] != canonical["number"]]
        for issue in open_issues:
            github(f"issues/{issue['number']}", method="PATCH", body={"state": "closed"})
    return active


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    modes.add_parser("deployed").add_argument("observation", type=Path)
    modes.add_parser("weekly")
    modes.add_parser("coverage")
    args = parser.parse_args()
    events = {"workflow_dispatch", "schedule"} if args.mode == "coverage" else {"workflow_dispatch"}
    if (
        os.environ["GITHUB_REF"] != "refs/heads/main"
        or os.environ["GITHUB_EVENT_NAME"] not in events
        or not os.environ["GH_TOKEN"]
    ):
        raise ValueError("Issue reconciliation requires a trusted run on main")
    if args.mode == "deployed":
        reports = deployed_reports(json.loads(args.observation.read_text()), datetime.now(UTC))
    elif args.mode == "weekly":
        reports = weekly_reports(json.loads(os.environ["AUDIT_RESULTS"]))
    else:
        reports = coverage_reports(datetime.now(UTC))
    active = reconcile(args.mode, reports, close_missing=args.mode == "deployed")
    repo_url = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
    links = ", ".join(f"[#{n}]({repo_url}/issues/{n})" for n in active)
    summary = f"Observed {len(active)} actionable {args.mode} issues. {links}".strip()
    print(summary)
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as stream:
        stream.write(summary + "\n")


if __name__ == "__main__":
    main()
