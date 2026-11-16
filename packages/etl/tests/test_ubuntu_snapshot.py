"""Authenticate OS updates before rendering any deployment inputs."""

import hashlib
import importlib.util
import json
import lzma
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "ubuntu_update", ROOT / "packages/etl/scripts/update_ubuntu_snapshot.py"
)
assert spec and spec.loader
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def test_index_bytes_and_size_must_match_signed_release():
    data = b"authenticated index"
    path = "main/binary-amd64/Packages.xz"
    release = f"\nSHA256:\n {hashlib.sha256(data).hexdigest()} {len(data)} {path}\n"
    updater.verify_index(release, path, data)
    with pytest.raises(ValueError):
        updater.verify_index(release, path, data + b"tampered")
    with pytest.raises(ValueError):
        updater.verify_index(release.replace(str(len(data)), "999"), path, data)


def test_unsafe_package_paths_cannot_become_docker_inputs():
    record = (
        "Package: openssl\nArchitecture: amd64\nVersion: 3.5.5-1ubuntu3.7\n"
        "Filename: pool/../../evil.deb\nSHA256: " + "a" * 64
    )
    with pytest.raises(ValueError, match="Unsafe"):
        list(updater.package_records(lzma.compress(record.encode()), {"openssl"}))


def test_snapshot_downgrade_and_future_snapshot_are_refused(tmp_path):
    for snapshot in ("20000101T000000Z", "20990101T000000Z"):
        with pytest.raises(ValueError):
            updater.resolve({"snapshot": "20261115T000000Z"}, snapshot, tmp_path / "keyring")


def test_render_keeps_chrome_and_bubblewrap_pins(tmp_path):
    old = json.loads((ROOT / updater.LOCK).read_text())
    new = json.loads(json.dumps(old))
    new["snapshot"] = "20261116T000000Z"
    new["packages"]["libc6"]["version"] = "2.43-2ubuntu2.8"
    new["bootstrap"]["openssl"] = {
        "url": "https://snapshot.ubuntu.com/openssl.deb",
        "sha256": "b" * 64,
    }
    for path in updater.CONSUMERS:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        original = (ROOT / path).read_text()
        rendered = updater.render(original, old, new)
        target.write_text(rendered)
        assert "157.0.8103.78" in rendered or "${chrome_package_version}" in rendered
        assert "0.12.0-0philly1" in rendered
        assert "2.43-2ubuntu2.8" in rendered
    updater.check(tmp_path, new)
