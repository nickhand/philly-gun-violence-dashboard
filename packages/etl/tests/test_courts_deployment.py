"""Deployment gates preserve court work and reject partial or mismatched evidence."""

import copy
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from etl.courts import deployment

SCRIPT = Path(__file__).resolve().parents[3] / ".github/ci/deploy_scraper.py"
SPEC = importlib.util.spec_from_file_location("deploy_scraper", SCRIPT)
assert SPEC and SPEC.loader
CI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CI)


@pytest.fixture
def release():
    return deployment.CourtsRelease(
        source_sha="a" * 40,
        chrome_lock_sha256="b" * 64,
        worker="ujs-scraper:13",
        monitor="ujs-scraper-monitor:7",
        image="123456789012.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper@sha256:" + "c" * 64,
    )


def test_lock_hash_ignores_only_json_formatting():
    assert deployment.lock_digest(b'{"a":1, "b":2}') == deployment.lock_digest(b'{"b": 2, "a": 1}')
    assert deployment.lock_digest(b'{"a":1}') != deployment.lock_digest(b'{"a":2}')


def test_enabled_pointer_never_falls_back_on_access_errors(monkeypatch):
    monkeypatch.setenv("COURTS_RELEASE_KEY", "ujs-scraper/deployment/active.json")
    monkeypatch.setattr(deployment, "CourtsSubmitterConfig", lambda: Mock())
    monkeypatch.setattr(deployment, "read_release", Mock(side_effect=RuntimeError("missing")))
    with pytest.raises(RuntimeError, match="missing"):
        deployment.load_release_environment(Mock(), Mock())


def test_loader_validates_both_definitions_before_export(monkeypatch, release):
    monkeypatch.setenv("COURTS_RELEASE_KEY", "ujs-scraper/deployment/active.json")
    monkeypatch.setattr(deployment, "CourtsSubmitterConfig", lambda **kwargs: Mock())
    monkeypatch.setattr(deployment, "read_release", Mock(return_value=(release, "etag")))
    resolve = Mock()
    monkeypatch.setattr(deployment, "resolve_split_task_definitions", resolve)
    assert deployment.load_release_environment(Mock(), Mock()) == release.pins()
    resolve.assert_called_once()
    resolve.side_effect = RuntimeError("bad definition")
    with pytest.raises(RuntimeError, match="bad definition"):
        deployment.load_release_environment(Mock(), Mock())


def test_pointer_schema_rejects_unknown_fields_and_key_substitution(release):
    s3 = Mock()
    config = SimpleNamespace(s3_bucket="bucket", s3_scraper_prefix="ujs-scraper")
    with pytest.raises(ValueError, match="reviewed"):
        deployment.read_release(s3, config, "ujs-scraper/runs/manifest.json")
    s3.get_object.assert_not_called()
    body = release.model_dump() | {"AWS_ACCESS_KEY_ID": "never-export"}
    s3.get_object.return_value = {"ETag": "etag", "Body": io.BytesIO(json.dumps(body).encode())}
    with pytest.raises(ValueError):
        deployment.read_release(s3, config, "ujs-scraper/deployment/active.json")


@pytest.fixture
def probe(release):
    config = SimpleNamespace(
        ecs_task_definition=release.worker,
        ecs_monitor_task_definition=release.monitor,
        ecs_container_name="ujs-scraper",
        ecs_expected_image_uri=release.image,
        ecs_security_group_ids=["sg-a"],
        ecs_subnet_ids=["subnet-a"],
    )
    task = {
        "taskDefinitionArn": release.worker,
        "lastStatus": "STOPPED",
        "desiredStatus": "STOPPED",
        "launchType": "FARGATE",
        "platformVersion": "1.4.0",
        "platformFamily": "Linux",
        "enableExecuteCommand": False,
        "containers": [
            {
                "name": "ujs-scraper",
                "exitCode": 0,
                "image": release.image,
                "imageDigest": release.image.split("@")[1],
            }
        ],
        "attachments": [
            {
                "type": "ElasticNetworkInterface",
                "details": [
                    {"name": "networkInterfaceId", "value": "eni-a"},
                    {"name": "subnetId", "value": "subnet-a"},
                ],
            }
        ],
    }
    interfaces = [
        {"NetworkInterfaceId": "eni-a", "SubnetId": "subnet-a", "Groups": [{"GroupId": "sg-a"}]}
    ]
    return task, interfaces, ["COURTS_FARGATE_SMOKE_OK_V1"], config, "worker"


def test_exact_live_probe_passes(probe):
    CI.verify_probe(*probe)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda task, eni, logs: task.update(enableExecuteCommand=True),
        lambda task, eni, logs: task.update(platformVersion="LATEST"),
        lambda task, eni, logs: task.update(taskDefinitionArn="ujs-scraper:99"),
        lambda task, eni, logs: task["containers"][0].update(exitCode=137),
        lambda task, eni, logs: task["containers"][0].update(imageDigest="sha256:" + "f" * 64),
        lambda task, eni, logs: eni[0]["Groups"].append({"GroupId": "sg-extra"}),
        lambda task, eni, logs: eni[0].update(NetworkInterfaceId="eni-other"),
        lambda task, eni, logs: eni.clear(),
        lambda task, eni, logs: logs.clear(),
        lambda task, eni, logs: logs.append("COURTS_FARGATE_SMOKE_OK_V1"),
    ],
)
def test_probe_mismatches_block_promotion(probe, mutation):
    task, eni, logs, config, role = copy.deepcopy(probe)
    mutation(task, eni, logs)
    with pytest.raises(RuntimeError):
        CI.verify_probe(task, eni, logs, config, role)


def test_monitor_requires_clean_health(probe):
    task, eni, _, config, _ = probe
    task["taskDefinitionArn"] = config.ecs_monitor_task_definition
    CI.verify_probe(task, eni, ['{"healthy":true,"findings":[]}'], config, "monitor")
    with pytest.raises(RuntimeError, match="health"):
        CI.verify_probe(task, eni, ['{"healthy":true,"findings":["stale"]}'], config, "monitor")


@pytest.fixture
def operator(monkeypatch, release, tmp_path):
    op = object.__new__(CI.Deployment)
    op.s3 = Mock()
    op.ecs = Mock()
    op.base = op.config = SimpleNamespace(s3_bucket="bucket")
    op.key = "ujs-scraper/deployment/active.json"
    op.current, op.etag = release, "before"
    op.idle = Mock(return_value=True)
    op.snapshot = Mock(return_value={"lease": "unchanged"})
    candidate = deployment.CourtsRelease.model_validate(
        release.model_dump() | {"worker": "ujs-scraper:14"}
    )
    state = {
        "before": release.model_dump(),
        "before_etag": "before",
        "candidate": candidate.model_dump(),
        "court_snapshot": op.snapshot(),
        "verify_only": False,
    }
    monkeypatch.setattr(CI, "EVIDENCE", tmp_path)
    CI.save("state.json", state)
    for role in ("worker", "monitor"):
        definition = candidate.worker if role == "worker" else candidate.monitor
        CI.save(
            f"{role}-verified.json",
            {"verified": True, "image": candidate.image, "definition": definition},
        )
    monkeypatch.setattr(CI, "require_current_main", Mock())
    monkeypatch.setattr(CI, "summary", Mock())
    monkeypatch.setattr(CI, "resolve_split_task_definitions", Mock())
    monkeypatch.setattr(deployment.CourtsRelease, "config", Mock(return_value=op.config))
    op.s3.put_object.return_value = {"ETag": "candidate"}
    monkeypatch.setattr(CI, "read_release", Mock(return_value=(candidate, "candidate")))
    return op


def test_atomic_promotion_uses_original_etag_and_retains_rollback(operator):
    operator.promote()
    args = operator.s3.put_object.call_args.kwargs
    assert args["IfMatch"] == "before"
    assert json.loads(args["Body"])["worker"] == "ujs-scraper:14"
    assert CI.read("promotion.json")["previous"]["worker"] == "ujs-scraper:13"


@pytest.mark.parametrize("change", ["busy", "court", "pointer", "etag", "main"])
def test_pre_promotion_changes_never_write(operator, change, monkeypatch):
    if change == "busy":
        operator.idle.return_value = False
    elif change == "court":
        operator.snapshot.return_value = {"lease": "changed"}
    elif change == "pointer":
        operator.current = deployment.CourtsRelease.model_validate(
            operator.current.model_dump() | {"worker": "ujs-scraper:99"}
        )
    elif change == "etag":
        operator.etag = "somebody-else"
    else:
        monkeypatch.setattr(CI, "require_current_main", Mock(side_effect=RuntimeError("stale")))
    with pytest.raises(RuntimeError):
        operator.promote()
    operator.s3.put_object.assert_not_called()


def test_post_promotion_failure_rolls_back_only_our_generation(operator):
    operator.snapshot.side_effect = [{"lease": "unchanged"}, {"lease": "changed"}]
    with pytest.raises(RuntimeError, match="Post-promotion"):
        operator.promote()
    writes = operator.s3.put_object.call_args_list
    assert len(writes) == 2
    assert writes[1].kwargs["IfMatch"] == "candidate"
    assert json.loads(writes[1].kwargs["Body"])["worker"] == "ujs-scraper:13"
    assert CI.read("rollback.json")["status"] == "rolled_back"


def test_failed_cas_does_not_overwrite_another_promotion(operator):
    operator.s3.put_object.side_effect = ClientError(
        {"Error": {"Code": "PreconditionFailed"}}, "PutObject"
    )
    with pytest.raises(ClientError):
        operator.promote()
    assert operator.s3.put_object.call_count == 1


def test_lost_write_response_reconciles_and_rolls_back_our_commit(operator):
    operator.s3.put_object.side_effect = [ConnectionError("response lost"), {"ETag": "restored"}]
    with pytest.raises(ConnectionError, match="response lost"):
        operator.promote()
    writes = operator.s3.put_object.call_args_list
    assert len(writes) == 2
    assert writes[1].kwargs["IfMatch"] == "candidate"
    assert json.loads(writes[1].kwargs["Body"])["worker"] == "ujs-scraper:13"


def test_latest_main_validation_cannot_reuse_an_older_success(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", CI.REPO)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(CI.subprocess, "check_output", Mock(return_value="a" * 40))
    runs = [
        {
            "headSha": "a" * 40,
            "databaseId": 1,
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        },
        {
            "headSha": "a" * 40,
            "databaseId": 2,
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "failure",
        },
    ]
    monkeypatch.setattr(CI, "command_json", Mock(side_effect=[{"object": {"sha": "a" * 40}}, runs]))
    with pytest.raises(RuntimeError, match="ETL quality"):
        CI.require_current_main()


def test_verify_only_does_not_publish(operator):
    state = CI.read("state.json")
    state["verify_only"] = True
    CI.save("state.json", state)
    operator.promote()
    operator.s3.put_object.assert_not_called()


def test_busy_courts_defer_without_building_or_writing(operator, monkeypatch):
    operator.idle.return_value = False
    operator.snapshot.reset_mock()
    emit = Mock()
    monkeypatch.setattr(CI, "output", emit)
    operator.plan(verify_only=False, force=True)
    emit.assert_called_once_with("ready", "false")
    operator.snapshot.assert_not_called()
    operator.s3.put_object.assert_not_called()


def test_already_deployed_lock_is_a_noop(operator, monkeypatch):
    monkeypatch.setattr(CI, "lock_digest", lambda _: operator.current.chrome_lock_sha256)
    emit = Mock()
    monkeypatch.setattr(CI, "output", emit)
    operator.plan(verify_only=False)
    emit.assert_called_once_with("ready", "false")
    operator.idle.assert_not_called()


def test_probe_for_another_definition_cannot_promote(operator):
    proof = CI.read("worker-verified.json") | {"definition": "ujs-scraper:99"}
    CI.save("worker-verified.json", proof)
    with pytest.raises(RuntimeError, match="probe proof"):
        operator.promote()
    operator.s3.put_object.assert_not_called()
