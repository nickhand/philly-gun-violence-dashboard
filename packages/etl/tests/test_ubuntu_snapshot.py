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
    chrome_version = json.loads((ROOT / "packages/etl/chrome-lock.json").read_text())["package"][
        "product_version"
    ]
    for path in updater.CONSUMERS:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        original = (ROOT / path).read_text()
        rendered = updater.render(original, old, new)
        target.write_text(rendered)
        chrome_pin = (
            "${chrome_package_version}"
            if "${chrome_package_version}" in original
            else chrome_version
        )
        assert original.count(chrome_pin) > 0
        assert rendered.count(chrome_pin) == original.count(chrome_pin)
        assert "0.12.0-0philly1" in rendered
        assert "2.43-2ubuntu2.8" in rendered
    updater.check(tmp_path, new)


def test_unexpected_archive_signer_is_rejected(monkeypatch, tmp_path):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    snapshot = datetime.now(UTC).strftime("%Y%m%dT000000Z")
    monkeypatch.setattr(updater, "download", lambda *a: b"signed metadata")
    monkeypatch.setattr(
        updater.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout="[GNUPG:] VALIDSIG WRONG "),
    )
    with pytest.raises(ValueError, match="Unexpected Ubuntu archive signer"):
        updater.resolve({"snapshot": snapshot}, snapshot, tmp_path / "keyring")


def test_signed_package_downgrade_is_still_rejected(monkeypatch, tmp_path):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    snapshot = datetime.now(UTC).strftime("%Y%m%dT000000Z")
    monkeypatch.setattr(updater, "download", lambda *a: b"signed metadata")
    monkeypatch.setattr(
        updater.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout=f"[GNUPG:] VALIDSIG {updater.ARCHIVE_SIGNER} "),
    )
    monkeypatch.setattr(updater, "verify_index", lambda *a: None)
    monkeypatch.setattr(updater, "package_records", lambda *a: [("openssl", {"version": "1"})])
    monkeypatch.setattr(updater, "version_at_least", lambda left, right: int(left) >= int(right))
    with pytest.raises(ValueError, match="Package downgrade refused"):
        updater.resolve(
            {"snapshot": snapshot, "packages": {"openssl": {"version": "2"}}},
            snapshot,
            tmp_path / "keyring",
        )
