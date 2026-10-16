"""Release the exact green main commit; preserve active court work and all gates."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import signal
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import boto3
from aws_batch_scraper import release_image
from aws_batch_scraper.health import check_run_health
from aws_batch_scraper.lease import read_run_lease
from aws_batch_scraper.orchestrate import _network_config, resolve_split_task_definitions
from botocore.exceptions import ClientError
from etl.courts.config import CourtsSubmitterConfig
from etl.courts.deployment import CourtsRelease, lock_digest, read_release

REPO = "nickhand/philly-gun-violence-dashboard"
ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".artifacts/scraper-deploy"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command_json(*args):
    return json.loads(subprocess.check_output(args, text=True))


def save(name, value):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / name).write_text(json.dumps(value, indent=2, default=str) + "\n")


def read(name):
    return json.loads((EVIDENCE / name).read_text())


def output(name, value):
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write(f"{name}={value}\n")


def summary(message):
    print(message, flush=True)
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as stream:
        stream.write(message + "\n")


def require_current_main():
    require(os.environ.get("GITHUB_REPOSITORY") == REPO, "Unexpected repository")
    require(os.environ.get("GITHUB_REF") == "refs/heads/main", "Only main can deploy")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    current = command_json("gh", "api", f"repos/{REPO}/git/ref/heads/main")["object"]["sha"]
    require(sha == current, "Main advanced; leave production unchanged and retry latest main")
    runs = command_json(
        "gh",
        "run",
        "list",
        "--repo",
        REPO,
        "--workflow",
        "etl-quality.yml",
        "--branch",
        "main",
        "--commit",
        sha,
        "--limit",
        "30",
        "--json",
        "databaseId,headSha,event,status,conclusion",
    )
    matching = [
        r for r in runs if r["headSha"] == sha and r["event"] in {"push", "workflow_dispatch"}
    ]
    latest = max(matching, key=lambda r: r["databaseId"], default={})
    require(
        latest.get("status") == "completed" and latest.get("conclusion") == "success",
        "The exact main commit must pass ETL quality before deployment",
    )
    return sha


def verify_probe(task, interfaces, messages, config, role):
    definition = (
        config.ecs_task_definition if role == "worker" else config.ecs_monitor_task_definition
    )
    require(task["taskDefinitionArn"] == definition, "Probe used another task definition")
    require(task["lastStatus"] == task["desiredStatus"] == "STOPPED", "Probe did not stop")
    require(
        task["launchType"] == "FARGATE"
        and task["platformVersion"] == "1.4.0"
        and task["platformFamily"] == "Linux"
        and task["enableExecuteCommand"] is False,
        "Probe platform or execute-command mismatch",
    )
    require(len(task["containers"]) == 1, "Unexpected probe containers")
    container = task["containers"][0]
    require(
        container["name"] == config.ecs_container_name and container.get("exitCode") == 0,
        "Probe container failed",
    )
    require(
        container["image"] == config.ecs_expected_image_uri
        and container["imageDigest"] == config.ecs_expected_image_uri.split("@")[1],
        "Probe image mismatch",
    )
    require(len(interfaces) == 1, "Missing authoritative network evidence")
    eni = interfaces[0]
    require(
        {g["GroupId"] for g in eni["Groups"]} == set(config.ecs_security_group_ids),
        "Probe security-group set mismatch",
    )
    details = [
        {d["name"]: d["value"] for d in a["details"]}
        for a in task["attachments"]
        if a["type"] == "ElasticNetworkInterface"
    ]
    require(
        len(details) == 1
        and details[0]["networkInterfaceId"] == eni["NetworkInterfaceId"]
        and details[0]["subnetId"] == eni["SubnetId"]
        and eni["SubnetId"] in config.ecs_subnet_ids,
        "Probe ENI/subnet mismatch",
    )
    if role == "worker":
        require(
            sum(m.count("COURTS_FARGATE_SMOKE_OK_V1") for m in messages) == 1,
            "Missing or duplicate live Chrome success marker",
        )
    else:
        reports = [json.loads(m) for m in messages if m.startswith("{") and '"healthy"' in m]
        require(
            len(reports) == 1 and reports[0]["healthy"] is True and reports[0]["findings"] == [],
            "Monitor health failed",
        )


class Deployment:
    def __init__(self):
        self.session = boto3.Session(region_name=os.environ["AWS_REGION"])
        self.base = CourtsSubmitterConfig()
        require(
            self.session.client("sts").get_caller_identity()["Account"] == self.base.aws_account_id,
            "Wrong AWS account",
        )
        self.s3 = self.session.client("s3")
        self.ecs = self.session.client("ecs")
        self.key = os.environ["COURTS_RELEASE_KEY"]
        self.current, self.etag = read_release(self.s3, self.base, self.key)
        self.config = self.current.config()
        resolve_split_task_definitions(self.ecs, self.config)

    def idle(self):
        tasks = []
        for page in self.ecs.get_paginator("list_tasks").paginate(
            cluster=self.config.ecs_cluster_name
        ):
            tasks.extend(page["taskArns"])
        sqs = self.session.client("sqs")
        url = sqs.get_queue_url(QueueName=self.config.sqs_queue_name)["QueueUrl"]
        attrs = sqs.get_queue_attributes(
            QueueUrl=url,
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
                "ApproximateNumberOfMessagesDelayed",
            ],
        )["Attributes"]
        lease = read_run_lease(self.s3, self.config)
        return (
            not tasks
            and all(int(v) == 0 for v in attrs.values())
            and lease.expires_at <= datetime.now(UTC)
        )

    def snapshot(self):
        lease = read_run_lease(self.s3, self.config)
        run_id, findings = check_run_health(self.s3, self.ecs, self.config)
        require(run_id == lease.run_id and not findings, f"Court run is unhealthy: {findings}")
        key = f"{self.config.s3_scraper_prefix}/runs/{run_id}/manifest.json"
        body = self.s3.get_object(Bucket=self.config.s3_bucket, Key=key)["Body"].read()
        require(json.loads(body).get("completed_at") is not None, "Court run is not completed")
        return {
            "lease": lease.model_dump(mode="json"),
            "manifest_sha256": hashlib.sha256(body).hexdigest(),
        }

    def plan(self, verify_only, force=False):
        sha = require_current_main()
        lock = lock_digest((ROOT / "packages/etl/chrome-lock.json").read_bytes())
        if lock == self.current.chrome_lock_sha256 and not verify_only and not force:
            summary("The merged Chrome release is already deployed.")
            output("ready", "false")
            return
        if not self.idle():
            summary(
                "Deployment deferred: court work is active. "
                "The daily Chrome check retries automatically."
            )
            output("ready", "false")
            return
        state = {
            "source_sha": sha,
            "chrome_lock_sha256": lock,
            "verify_only": verify_only,
            "before": self.current.model_dump(),
            "before_etag": self.etag,
            "court_snapshot": self.snapshot(),
        }
        save("state.json", state)
        output("ready", "true")

    def build(self, state):
        target = release_image.ReleaseTarget(
            self.config.aws_account_id, "ujs-scraper", self.config.aws_region, state["source_sha"]
        )
        release_image.validate_release_source(target.tag)
        release_image.require_immutable_repository(target)
        ecr = self.session.client("ecr")
        try:
            existing = ecr.describe_images(
                repositoryName=target.repository, imageIds=[{"imageTag": target.tag}]
            )["imageDetails"]
        except ecr.exceptions.ImageNotFoundException:
            existing = []
        auth = ecr.get_authorization_token(registryIds=[target.account_id])["authorizationData"]
        registry = target.repository_uri.split("/", 1)[0]
        remote_tag = f"{target.repository_uri}:{target.tag}"
        require(
            len(auth) == 1 and auth[0]["proxyEndpoint"] == f"https://{registry}",
            "Unexpected ECR login endpoint",
        )
        username, password = base64.b64decode(auth[0]["authorizationToken"]).decode().split(":", 1)
        subprocess.run(
            ["docker", "login", "--username", username, "--password-stdin", registry],
            input=password,
            text=True,
            check=True,
        )
        image = f"ujs-scraper:{target.tag}"
        if existing:
            require(len(existing) == 1, "Ambiguous immutable image tag")
            remote = f"{target.repository_uri}@{existing[0]['imageDigest']}"
            subprocess.run(["docker", "pull", "--platform", "linux/amd64", remote], check=True)
            subprocess.run(["docker", "tag", remote, image], check=True)
        else:
            subprocess.run(
                ["python", ".github/ci/build_scraper_image.py", "--release-tag", target.tag],
                check=True,
            )
        release_image.verify_local_image(image, target.tag)
        subprocess.run(["bash", ".github/ci/smoke_scraper_image.sh", image], check=True)
        package_line = re.findall(
            r'^aws_batch_scraper_required_sbom_packages := "([^"\n]+)"$',
            (ROOT / "Justfile").read_text(),
            re.MULTILINE,
        )
        require(len(package_line) == 1, "Missing exact SBOM package policy")
        lock = json.loads((ROOT / "packages/etl/chrome-lock.json").read_text())
        scan_dir = EVIDENCE / "release"
        receipt = release_image.scan_local_image(
            image,
            requirements=release_image.parse_package_requirements(package_line[0]),
            expected_distro_name="ubuntu",
            expected_distro_version="26.04",
            expected_chrome_executable_sha256=f"sha256:{lock['executable']['sha256']}",
            forbid_chrome_sandbox=True,
            forbid_setuid_setgid_files=True,
            output_directory=scan_dir,
        )
        image_id = receipt["image"]["id"]
        if not existing:
            release_image.preflight_release(target)
            subprocess.run(["docker", "tag", image_id, remote_tag], check=True)
            subprocess.run(["docker", "push", remote_tag], check=True)
        digest = release_image.verify_remote_scan(target, expected_image_id=image_id)
        release_image.write_verified_release_receipt(
            scan_dir / "receipt.json",
            scan_dir / "release.json",
            target=target,
            digest=digest,
            expected_image_id=image_id,
        )
        return f"{target.repository_uri}@{digest}"

    def register(self, state, image):
        allowed = self.ecs.meta.service_model.operation_model(
            "RegisterTaskDefinition"
        ).input_shape.members
        arns = []
        for role, old_arn in [("worker", self.current.worker), ("monitor", self.current.monitor)]:
            old = self.ecs.describe_task_definition(taskDefinition=old_arn, include=["TAGS"])
            request = {
                k: copy.deepcopy(v) for k, v in old["taskDefinition"].items() if k in allowed
            }
            request["containerDefinitions"][0]["image"] = image
            if old.get("tags"):
                request["tags"] = old["tags"]
            result = self.ecs.register_task_definition(**request)
            save(f"{role}-definition.json", result)
            arns.append(result["taskDefinition"]["taskDefinitionArn"])
        return CourtsRelease(
            source_sha=state["source_sha"],
            chrome_lock_sha256=state["chrome_lock_sha256"],
            worker=arns[0],
            monitor=arns[1],
            image=image,
        )

    def probe(self, release, role):
        config = release.config()
        resolve_split_task_definitions(self.ecs, config)
        require(self.idle(), "Court work started; do not launch a probe")
        definition = release.worker if role == "worker" else release.monitor
        # This explicit list cannot forward runner credentials or dispatch secrets.
        names = (
            "AWS_ACCOUNT_ID",
            "AWS_REGION",
            "S3_BUCKET",
            "S3_SCRAPER_PREFIX",
            "S3_PROCESSED_PREFIX",
            "S3_REFERENCE_PREFIX",
            "SQS_QUEUE_NAME",
            "SQS_DLQ_NAME",
            "ECS_CLUSTER_NAME",
            "ECS_CONTAINER_NAME",
            "ECS_EXPECTED_TASK_ROLE_ARN",
            "ECS_EXPECTED_EXECUTION_ROLE_ARN",
            "ECS_EXPECTED_MONITOR_SECRET_ARN",
            "ECS_SUBNET_IDS",
            "ECS_SECURITY_GROUP_IDS",
        )
        env = {name: os.environ[name] for name in names}
        env.update(release.pins(), ENV="prod", GITHUB_REPOSITORY=REPO, ECS_PLATFORM_VERSION="1.4.0")
        request = dict(
            cluster=config.ecs_cluster_name,
            taskDefinition=definition,
            count=1,
            launchType="FARGATE",
            platformVersion="1.4.0",
            enableExecuteCommand=False,
            networkConfiguration=_network_config(config),
            clientToken=str(uuid.uuid4()),
            startedBy=f"chrome-deploy-{os.environ['GITHUB_RUN_ID']}",
            tags=[{"key": "ManagedBy", "value": "chrome-deploy"}],
            overrides={
                "containerOverrides": [
                    {
                        "name": config.ecs_container_name,
                        "command": [
                            "gv-dashboard-etl",
                            "courts",
                            "fargate-smoke" if role == "worker" else "health",
                        ],
                        "environment": [{"name": k, "value": v} for k, v in sorted(env.items())],
                    }
                ]
            },
        )
        save(f"{role}-request.json", request)
        launch = self.ecs.run_task(**request)
        save(f"{role}-launch.json", launch)
        require(
            not launch.get("failures") and len(launch.get("tasks", [])) == 1, "Probe launch failed"
        )
        arn = launch["tasks"][0]["taskArn"]
        eni = None
        stopped = False
        try:
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                result = self.ecs.describe_tasks(cluster=config.ecs_cluster_name, tasks=[arn])
                require(
                    not result.get("failures") and len(result["tasks"]) == 1,
                    "Missing exact probe task",
                )
                task = result["tasks"][0]
                save(f"{role}-task.json", task)
                if eni is None:
                    for attachment in task.get("attachments", []):
                        if attachment["type"] == "ElasticNetworkInterface":
                            details = {d["name"]: d["value"] for d in attachment["details"]}
                            if "networkInterfaceId" in details:
                                eni = self.session.client("ec2").describe_network_interfaces(
                                    NetworkInterfaceIds=[details["networkInterfaceId"]]
                                )["NetworkInterfaces"]
                                save(f"{role}-eni.json", eni)
                if task["lastStatus"] == "STOPPED":
                    stopped = True
                    break
                time.sleep(5)
            require(stopped, "Probe did not stop within ten minutes")
            options = self.ecs.describe_task_definition(taskDefinition=definition)[
                "taskDefinition"
            ]["containerDefinitions"][0]["logConfiguration"]["options"]
            log_request = dict(
                logGroupName=options["awslogs-group"],
                logStreamName=(
                    f"{options['awslogs-stream-prefix']}/{config.ecs_container_name}/"
                    f"{arn.rsplit('/', 1)[1]}"
                ),
                startFromHead=True,
            )
            logs = self.session.client("logs")
            messages = []
            while True:
                response = logs.get_log_events(**log_request)
                messages.extend(event["message"] for event in response["events"])
                if response["nextForwardToken"] == log_request.get("nextToken"):
                    break
                log_request["nextToken"] = response["nextForwardToken"]
            save(f"{role}-logs.json", messages)
            verify_probe(task, eni or [], messages, config, role)
            require(self.idle(), "Probe or court task remains active")
            save(
                f"{role}-verified.json",
                {
                    "taskArn": arn,
                    "definition": definition,
                    "image": release.image,
                    "verified": True,
                },
            )
        finally:
            if not stopped:
                # Never stop a court worker: this ARN came only from our one-shot RunTask.
                self.ecs.stop_task(
                    cluster=config.ecs_cluster_name,
                    task=arn,
                    reason="Chrome deployment probe cleanup",
                )

    def prepare(self):
        state = read("state.json")
        require_current_main()
        require(
            self.current.model_dump() == state["before"] and self.etag == state["before_etag"],
            "Production release changed since planning",
        )
        require(self.idle() and self.snapshot() == state["court_snapshot"], "Court work changed")
        candidate = (
            self.current if state["verify_only"] else self.register(state, self.build(state))
        )
        state["candidate"] = candidate.model_dump()
        save("state.json", state)
        for role in ("worker", "monitor"):
            self.probe(candidate, role)
        require(self.snapshot() == state["court_snapshot"], "Court evidence changed during probes")
        output("verified", "true")
        summary(f"Live worker and monitor probes passed for `{candidate.image}`.")

    def promote(self):
        state = read("state.json")
        require_current_main()
        candidate = CourtsRelease.model_validate(state["candidate"])
        for role in ("worker", "monitor"):
            proof = read(f"{role}-verified.json")
            expected = candidate.worker if role == "worker" else candidate.monitor
            require(
                proof["verified"] is True
                and proof["image"] == candidate.image
                and proof["definition"] == expected,
                "Missing probe proof",
            )
        require(
            self.current.model_dump() == state["before"] and self.etag == state["before_etag"],
            "Production release changed; refusing to overwrite it",
        )
        require(self.idle() and self.snapshot() == state["court_snapshot"], "Court work changed")
        resolve_split_task_definitions(self.ecs, candidate.config())
        if state["verify_only"]:
            summary("Deployment automation verified end to end; production pins are unchanged.")
            return
        new_etag = None
        try:
            result = self.s3.put_object(
                Bucket=self.config.s3_bucket,
                Key=self.key,
                Body=candidate.model_dump_json(indent=2).encode(),
                ContentType="application/json",
                IfMatch=self.etag,
            )
            new_etag = result["ETag"]
            live, etag = read_release(self.s3, self.base, self.key)
            require(live == candidate and etag == new_etag, "Promoted release read-back mismatch")
            require(
                self.idle() and self.snapshot() == state["court_snapshot"],
                "Post-promotion court health changed",
            )
            save(
                "promotion.json",
                {
                    "status": "promoted",
                    "release": candidate.model_dump(),
                    "previous": state["before"],
                    "etag": new_etag,
                    "at": datetime.now(UTC).isoformat(),
                },
            )
        except BaseException as exc:
            # A lost PutObject response can still mean the CAS committed. Read
            # back before deciding whether our exact generation needs rollback.
            conflict = isinstance(exc, ClientError) and exc.response.get("Error", {}).get(
                "Code"
            ) in {"PreconditionFailed", "412", "ConditionalRequestConflict"}
            if new_etag is None and not conflict:
                live, etag = read_release(self.s3, self.base, self.key)
                if live == candidate and etag != self.etag:
                    new_etag = etag
            if new_etag is not None:
                self.s3.put_object(
                    Bucket=self.config.s3_bucket,
                    Key=self.key,
                    Body=self.current.model_dump_json(indent=2).encode(),
                    ContentType="application/json",
                    IfMatch=new_etag,
                )
                save("rollback.json", {"status": "rolled_back", "release": state["before"]})
            raise
        summary(
            f"Promoted worker `{candidate.worker}` and monitor `{candidate.monitor}`. "
            "All health checks passed."
        )


def interrupted(signum, frame):
    raise RuntimeError(f"Deployment interrupted by signal {signum}")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "prepare", "promote"))
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    deployment = Deployment()
    if args.operation == "plan":
        deployment.plan(args.verify_only, args.force)
    else:
        getattr(deployment, args.operation)()
