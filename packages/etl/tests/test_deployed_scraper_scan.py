"""Bind publishable daily security observations to the active production generation."""

import importlib.util
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from etl.courts.deployment import CourtsRelease, lock_digest

SCRIPT = Path(__file__).resolve().parents[3] / ".github/ci/scan_deployed_scraper.py"
SPEC = importlib.util.spec_from_file_location("scan_deployed_scraper", SCRIPT)
assert SPEC and SPEC.loader
CI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CI)

ACCOUNT = "123456789012"
REGION = "us-east-1"
BUCKET = "test-bucket"
KEY = "ujs-scraper/deployment/active.json"
ETAG = '"active-generation"'
DIGEST = "sha256:" + "c" * 64
REPOSITORY = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/ujs-scraper"


@pytest.fixture
def services(monkeypatch, tmp_path):
    # Deliberately use an older, valid release than the lock in the checkout.
    lock = json.loads((SCRIPT.parents[2] / "packages/etl/chrome-lock.json").read_text())
    version = "154.0.1.1"
    package = lock["package"]
    package.update(
        version=version + "-1",
        product_version=version,
        filename=f"pool/main/g/google-chrome-stable/google-chrome-stable_{version}-1_amd64.deb",
    )
    lock["executable"]["sha256"] = "f" * 64
    contents = (json.dumps(lock) + "\n").encode()
    release = CourtsRelease(
        source_sha="a" * 40,
        chrome_lock_sha256=lock_digest(contents),
        worker="ujs-scraper:13",
        monitor="ujs-scraper-monitor:7",
        image=f"{REPOSITORY}@{DIGEST}",
    )
    s3 = Mock()
    s3.get_object.return_value = {
        "Body": io.BytesIO(release.model_dump_json().encode()),
        "ETag": ETAG,
    }
    s3.head_object.return_value = {"ETag": ETAG}
    monkeypatch.setattr(CI.boto3, "client", Mock(return_value=s3))
    git = Mock(return_value=contents)
    monkeypatch.setattr(CI.subprocess, "check_output", git)
    scan = Mock(return_value={"image": release.image, "findings": [], "observed_at": "outdated"})
    monkeypatch.setattr(CI, "scan_deployed_image", scan)
    monkeypatch.setenv("AWS_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("AWS_REGION", REGION)
    monkeypatch.setenv("S3_BUCKET", BUCKET)
    monkeypatch.setenv("COURTS_RELEASE_KEY", KEY)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary"))
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), str(tmp_path / "evidence"), str(tmp_path / "verified.json")],
    )
    return release, s3, git, scan


def test_daily_scan_verifies_deployed_lock_and_current_generation(services, tmp_path):
    release, s3, git, scan = services
    started = datetime.now(UTC)
    CI.main()
    git.assert_called_once_with(
        ["git", "show", f"{release.source_sha}:packages/etl/chrome-lock.json"]
    )
    target, digest = scan.call_args.args
    assert target.repository_uri == REPOSITORY and target.tag == release.source_sha
    assert digest == DIGEST
    policy = scan.call_args.kwargs
    assert [p.canonical for p in policy["requirements"]] == ["deb:google-chrome-stable=154.0.1.1-1"]
    assert policy["expected_chrome_executable_sha256"] == "sha256:" + "f" * 64
    s3.head_object.assert_called_once_with(Bucket=BUCKET, Key=KEY, IfMatch=ETAG)
    trusted = json.loads((tmp_path / "verified.json").read_text())
    assert trusted["image"] == release.image and trusted["findings"] == []
    certified = datetime.fromisoformat(trusted["observed_at"])
    assert certified.tzinfo == UTC and started <= certified <= datetime.now(UTC)


@pytest.mark.parametrize("bad_input", ["pointer", "etag", "digest", "repository", "lock"])
def test_unbound_release_inputs_never_reach_the_scanner(bad_input, services, tmp_path, monkeypatch):
    release, s3, git, scan = services
    if bad_input == "pointer":
        monkeypatch.setenv("COURTS_RELEASE_KEY", "other/pointer.json")
    elif bad_input == "etag":
        del s3.get_object.return_value["ETag"]
    elif bad_input == "lock":
        git.return_value = b'{"wrong":true}'
    else:
        image = f"{REPOSITORY}@main" if bad_input == "digest" else f"example.org/other@{DIGEST}"
        invalid = release.model_copy(update={"image": image})
        s3.get_object.return_value["Body"] = io.BytesIO(invalid.model_dump_json().encode())
    with pytest.raises(ValueError):
        CI.main()
    scan.assert_not_called()
    assert not (tmp_path / "verified.json").exists()


def test_concurrent_promotion_prevents_stale_observation_even_after_clean_scan(services, tmp_path):
    _, s3, _, scan = services
    s3.head_object.side_effect = ClientError(
        {"Error": {"Code": "PreconditionFailed"}}, "HeadObject"
    )
    with pytest.raises(ClientError, match="PreconditionFailed"):
        CI.main()
    scan.assert_called_once()
    assert not (tmp_path / "verified.json").exists()
