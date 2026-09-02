"""Tests for the signed stable Chrome freshness boundary."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

import etl.chrome_release as chrome_release
from etl.chrome_release import (
    CHROME_LOCK_PATH,
    GOOGLE_INRELEASE_URL,
    GOOGLE_PACKAGES_PATH,
    GOOGLE_PACKAGES_URL,
    GOOGLE_REPOSITORY_URL,
    GOOGLE_SIGNING_KEY_FINGERPRINT,
    GOOGLE_SIGNING_KEY_URL,
    PINNED_CHROME_EXECUTABLE_SHA256,
    PINNED_CHROME_FILENAME,
    PINNED_CHROME_PRODUCT_VERSION,
    PINNED_CHROME_SHA256,
    PINNED_CHROME_VERSION,
    ChromeReleaseError,
    load_chrome_lock,
    update_chrome_lock,
    verify_pinned_chrome_release,
)

NOW = datetime(2026, 8, 19, 17, tzinfo=UTC)


def test_exported_constants_come_from_authoritative_lock() -> None:
    lock = load_chrome_lock()

    assert CHROME_LOCK_PATH.name == "chrome-lock.json"
    assert lock.package.version == PINNED_CHROME_VERSION
    assert lock.package.product_version == PINNED_CHROME_PRODUCT_VERSION
    assert lock.package.filename == PINNED_CHROME_FILENAME
    assert lock.package.sha256 == PINNED_CHROME_SHA256
    assert lock.executable.sha256 == PINNED_CHROME_EXECUTABLE_SHA256


def _filename(version: str) -> str:
    return f"pool/main/g/google-chrome-stable/google-chrome-stable_{version}_amd64.deb"


def _newer_version() -> str:
    milestone = int(PINNED_CHROME_PRODUCT_VERSION.split(".", maxsplit=1)[0]) + 1
    return f"{milestone}.0.0.1-1"


def _older_version() -> str:
    milestone = int(PINNED_CHROME_PRODUCT_VERSION.split(".", maxsplit=1)[0]) - 1
    assert milestone > 0
    return f"{milestone}.0.0.1-1"


def _packages(
    *,
    version: str = PINNED_CHROME_VERSION,
    filename: str | None = None,
    sha256: str = PINNED_CHROME_SHA256,
) -> bytes:
    return (
        "Package: google-chrome-stable\n"
        "Architecture: amd64\n"
        f"Version: {version}\n"
        f"Filename: {filename or _filename(version)}\n"
        f"SHA256: {sha256}\n"
        "Description: browser\n"
    ).encode()


def _metadata(
    *,
    version: str = PINNED_CHROME_VERSION,
    filename: str | None = None,
    package_sha256: str = PINNED_CHROME_SHA256,
    publication_date: str = "Wed, 19 Aug 2026 16:14:15 UTC",
) -> tuple[bytes, bytes]:
    packages_gzip = gzip.compress(
        _packages(version=version, filename=filename, sha256=package_sha256),
        mtime=0,
    )
    digest = hashlib.sha256(packages_gzip).hexdigest()
    inrelease = (
        "Origin: Google LLC\n"
        "Suite: stable\n"
        "Codename: stable\n"
        f"Date: {publication_date}\n"
        "Architectures: amd64 arm64\n"
        "SHA256:\n"
        f" {digest} {len(packages_gzip)} {GOOGLE_PACKAGES_PATH}\n"
        "-----BEGIN PGP SIGNATURE-----\n"
    ).encode()
    return inrelease, packages_gzip


class StubRunner:
    """Return successful GPG results while retaining exact argument arrays."""

    def __init__(
        self,
        *,
        fingerprint: str = GOOGLE_SIGNING_KEY_FINGERPRINT,
        extra_primary_fingerprints: Sequence[str] = (),
        verified_inrelease: bytes | None = None,
    ) -> None:
        self.fingerprints = (fingerprint, *extra_primary_fingerprints)
        self.verified_inrelease = verified_inrelease
        self.calls: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(command))
        stdout = ""
        if "--show-keys" in command:
            stdout = "".join(
                f"pub:-:4096:1:key::::::\nfpr:::::::::{fingerprint}:\n"
                for fingerprint in self.fingerprints
            )
        elif command[0] == "gpgv":
            cleartext = self.verified_inrelease
            if cleartext is None:
                cleartext = Path(command[-1]).read_bytes()
            stdout = cleartext.decode()
        return subprocess.CompletedProcess(command, 0, stdout, "")


def _fetcher(
    inrelease: bytes,
    packages_gzip: bytes,
    extra_payloads: dict[str, bytes] | None = None,
):
    payloads = {
        GOOGLE_SIGNING_KEY_URL: b"public-key",
        GOOGLE_INRELEASE_URL: inrelease,
        GOOGLE_PACKAGES_URL: packages_gzip,
    }
    payloads.update(extra_payloads or {})

    def fetch(url: str, max_bytes: int) -> bytes:
        body = payloads[url]
        assert len(body) <= max_bytes
        return body

    return fetch


def test_signed_current_stable_package_passes() -> None:
    inrelease, packages_gzip = _metadata()
    runner = StubRunner()

    verify_pinned_chrome_release(
        fetcher=_fetcher(inrelease, packages_gzip),
        runner=runner,
        clock=lambda: NOW,
    )

    assert [call[0] for call in runner.calls] == ["gpg", "gpg", "gpgv"]
    assert "--keyring" in runner.calls[-1]


def test_new_stable_version_fails_until_pin_is_updated() -> None:
    next_version = _newer_version()
    inrelease, packages_gzip = _metadata(version=next_version)

    with pytest.raises(ChromeReleaseError, match=f"no longer.*observed {next_version}"):
        verify_pinned_chrome_release(
            fetcher=_fetcher(inrelease, packages_gzip),
            runner=StubRunner(),
            clock=lambda: NOW,
        )


def test_wrong_signing_key_fingerprint_fails() -> None:
    inrelease, packages_gzip = _metadata()

    with pytest.raises(ChromeReleaseError, match="fingerprint"):
        verify_pinned_chrome_release(
            fetcher=_fetcher(inrelease, packages_gzip),
            runner=StubRunner(fingerprint="A" * 40),
            clock=lambda: NOW,
        )


def test_additional_primary_signing_key_fails_closed() -> None:
    inrelease, packages_gzip = _metadata()
    runner = StubRunner(extra_primary_fingerprints=("A" * 40,))

    with pytest.raises(ChromeReleaseError, match="exactly one pinned primary fingerprint"):
        verify_pinned_chrome_release(
            fetcher=_fetcher(inrelease, packages_gzip),
            runner=runner,
            clock=lambda: NOW,
        )

    assert [call[0] for call in runner.calls] == ["gpg"]


def test_only_gpgv_authenticated_cleartext_is_parsed() -> None:
    verified_inrelease, packages_gzip = _metadata()
    untrusted_envelope = (
        b"Origin: Unsigned attacker preamble\n"
        + verified_inrelease
        + b"\nOrigin: Unsigned attacker trailer\n"
    )

    verify_pinned_chrome_release(
        fetcher=_fetcher(untrusted_envelope, packages_gzip),
        runner=StubRunner(verified_inrelease=verified_inrelease),
        clock=lambda: NOW,
    )


def test_replayed_signed_metadata_is_rejected_as_stale() -> None:
    inrelease, packages_gzip = _metadata(publication_date="Sat, 01 Aug 2026 16:14:15 UTC")

    with pytest.raises(ChromeReleaseError, match="metadata is stale"):
        verify_pinned_chrome_release(
            fetcher=_fetcher(inrelease, packages_gzip),
            runner=StubRunner(),
            clock=lambda: NOW,
        )


def test_packages_checksum_must_match_signed_inrelease() -> None:
    inrelease, packages_gzip = _metadata()
    corrupted = packages_gzip + b"corrupt"

    with pytest.raises(ChromeReleaseError, match="size did not match"):
        verify_pinned_chrome_release(
            fetcher=_fetcher(inrelease, corrupted),
            runner=StubRunner(),
            clock=lambda: NOW,
        )


def test_same_size_packages_tampering_fails_the_signed_checksum() -> None:
    inrelease, packages_gzip = _metadata()
    corrupted = bytearray(packages_gzip)
    corrupted[-1] ^= 1

    with pytest.raises(ChromeReleaseError, match="checksum did not match"):
        verify_pinned_chrome_release(
            fetcher=_fetcher(inrelease, bytes(corrupted)),
            runner=StubRunner(),
            clock=lambda: NOW,
        )


def test_signature_verification_failure_is_not_treated_as_stale_metadata() -> None:
    inrelease, packages_gzip = _metadata()

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if "--show-keys" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                f"pub:-:4096:1:key::::::\nfpr:::::::::{GOOGLE_SIGNING_KEY_FINGERPRINT}:\n",
                "",
            )
        if command[0] == "gpgv":
            return subprocess.CompletedProcess(command, 1, "", "bad signature")
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(ChromeReleaseError, match="signature verification failed"):
        verify_pinned_chrome_release(
            fetcher=_fetcher(inrelease, packages_gzip),
            runner=runner,
            clock=lambda: NOW,
        )


def _write_lock(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _lock_payload() -> dict[str, object]:
    return json.loads(CHROME_LOCK_PATH.read_text(encoding="utf-8"))


def test_lock_rejects_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "chrome-lock.json"
    payload = _lock_payload()
    payload["unexpected"] = True
    _write_lock(path, payload)

    with pytest.raises(ChromeReleaseError, match="unexpected: unexpected"):
        load_chrome_lock(path)


def test_lock_rejects_boolean_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "chrome-lock.json"
    payload = _lock_payload()
    payload["schema_version"] = True
    _write_lock(path, payload)

    with pytest.raises(ChromeReleaseError, match="schema_version"):
        load_chrome_lock(path)


def test_lock_rejects_inconsistent_product_version(tmp_path: Path) -> None:
    path = tmp_path / "chrome-lock.json"
    payload = _lock_payload()
    package = payload["package"]
    assert isinstance(package, dict)
    package["product_version"] = "1.2.3.4"
    _write_lock(path, payload)

    with pytest.raises(ChromeReleaseError, match="product_version did not match"):
        load_chrome_lock(path)


def test_lock_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "chrome-lock.json"
    source = CHROME_LOCK_PATH.read_text(encoding="utf-8")
    duplicate = source.replace(
        '"schema_version": 1,',
        '"schema_version": 1,\n  "schema_version": 1,',
        1,
    )
    path.write_text(duplicate, encoding="utf-8")

    with pytest.raises(ChromeReleaseError, match="duplicate key: schema_version"):
        load_chrome_lock(path)


def _ar_member(name: str, body: bytes) -> bytes:
    header = b"".join(
        (
            f"{name}/".encode("ascii").ljust(16),
            b"0".ljust(12),
            b"0".ljust(6),
            b"0".ljust(6),
            b"100644".ljust(8),
            str(len(body)).encode("ascii").ljust(10),
            b"`\n",
        )
    )
    assert len(header) == 60
    return header + body + (b"\n" if len(body) % 2 else b"")


def _chrome_deb(executable: bytes) -> bytes:
    data_archive = io.BytesIO()
    with tarfile.open(
        fileobj=data_archive,
        mode="w",
        format=tarfile.USTAR_FORMAT,
    ) as archive:
        member = tarfile.TarInfo("./opt/google/chrome/chrome")
        member.mode = 0o755
        member.mtime = 0
        member.size = len(executable)
        archive.addfile(member, io.BytesIO(executable))
    return (
        b"!<arch>\n"
        + _ar_member("debian-binary", b"2.0\n")
        + _ar_member("data.tar", data_archive.getvalue())
    )


def test_updater_authenticates_downloads_hashes_and_writes_only_when_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / "chrome-lock.json"
    lock_path.write_bytes(CHROME_LOCK_PATH.read_bytes())
    lock_path.chmod(0o640)
    version = _newer_version()
    filename = _filename(version)
    executable = b"verified chrome executable\x00"
    deb = _chrome_deb(executable)
    package_sha256 = hashlib.sha256(deb).hexdigest()
    inrelease, packages_gzip = _metadata(
        version=version,
        filename=filename,
        package_sha256=package_sha256,
    )
    runner = StubRunner()
    fetcher = _fetcher(
        inrelease,
        packages_gzip,
        {f"{GOOGLE_REPOSITORY_URL}/{filename}": deb},
    )

    result = update_chrome_lock(
        lock_path,
        fetcher=fetcher,
        runner=runner,
        clock=lambda: NOW,
    )

    assert result.changed is True
    assert result.lock.package.version == version
    assert result.lock.package.sha256 == package_sha256
    assert result.lock.executable.sha256 == hashlib.sha256(executable).hexdigest()
    assert load_chrome_lock(lock_path) == result.lock
    assert lock_path.stat().st_mode & 0o777 == 0o640
    assert {path.name for path in tmp_path.iterdir()} == {"chrome-lock.json"}
    rendered = lock_path.read_text(encoding="utf-8")
    assert rendered == json.dumps(json.loads(rendered), indent=2) + "\n"
    assert [call[0] for call in runner.calls] == ["gpg", "gpg", "gpgv"]

    def reject_replace(*_arguments: object) -> None:
        raise AssertionError("an unchanged lock must not be rewritten")

    monkeypatch.setattr(chrome_release.os, "replace", reject_replace)
    second = update_chrome_lock(
        lock_path,
        fetcher=fetcher,
        runner=StubRunner(),
        clock=lambda: NOW,
    )
    assert second.changed is False


def test_updater_rejects_deb_not_matching_signed_checksum(tmp_path: Path) -> None:
    lock_path = tmp_path / "chrome-lock.json"
    lock_path.write_bytes(CHROME_LOCK_PATH.read_bytes())
    original = lock_path.read_bytes()
    version = _newer_version()
    filename = _filename(version)
    deb = _chrome_deb(b"chrome")
    inrelease, packages_gzip = _metadata(
        version=version,
        filename=filename,
        package_sha256="f" * 64,
    )

    with pytest.raises(ChromeReleaseError, match="package checksum"):
        update_chrome_lock(
            lock_path,
            fetcher=_fetcher(
                inrelease,
                packages_gzip,
                {f"{GOOGLE_REPOSITORY_URL}/{filename}": deb},
            ),
            runner=StubRunner(),
            clock=lambda: NOW,
        )

    assert lock_path.read_bytes() == original
    assert {path.name for path in tmp_path.iterdir()} == {"chrome-lock.json"}


def test_updater_rejects_a_signed_version_rollback(tmp_path: Path) -> None:
    lock_path = tmp_path / "chrome-lock.json"
    lock_path.write_bytes(CHROME_LOCK_PATH.read_bytes())
    original = lock_path.read_bytes()
    version = _older_version()
    filename = _filename(version)
    deb = _chrome_deb(b"older signed chrome")
    package_sha256 = hashlib.sha256(deb).hexdigest()
    inrelease, packages_gzip = _metadata(
        version=version,
        filename=filename,
        package_sha256=package_sha256,
    )

    with pytest.raises(ChromeReleaseError, match="older signed stable release"):
        update_chrome_lock(
            lock_path,
            fetcher=_fetcher(
                inrelease,
                packages_gzip,
                {f"{GOOGLE_REPOSITORY_URL}/{filename}": deb},
            ),
            runner=StubRunner(),
            clock=lambda: NOW,
        )

    assert lock_path.read_bytes() == original
    assert {path.name for path in tmp_path.iterdir()} == {"chrome-lock.json"}


def test_cli_check_is_offline_and_read_only() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts/update_chrome_release.py"

    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(script), "check"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout == f"Chrome lock is valid: {PINNED_CHROME_VERSION}\n"
    assert completed.stderr == ""
