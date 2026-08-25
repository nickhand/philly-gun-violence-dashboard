"""Tests for the signed stable Chrome freshness boundary."""

from __future__ import annotations

import gzip
import hashlib
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from etl.chrome_release import (
    GOOGLE_INRELEASE_URL,
    GOOGLE_PACKAGES_PATH,
    GOOGLE_PACKAGES_URL,
    GOOGLE_SIGNING_KEY_FINGERPRINT,
    GOOGLE_SIGNING_KEY_URL,
    PINNED_CHROME_FILENAME,
    PINNED_CHROME_PRODUCT_VERSION,
    PINNED_CHROME_SHA256,
    PINNED_CHROME_VERSION,
    ChromeReleaseError,
    verify_pinned_chrome_release,
)

NOW = datetime(2026, 8, 19, 17, tzinfo=UTC)


def test_container_build_uses_the_same_reviewed_chrome_pin() -> None:
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()

    assert f"ADD --checksum=sha256:{PINNED_CHROME_SHA256}" in dockerfile
    assert f"https://dl.google.com/linux/chrome/deb/{PINNED_CHROME_FILENAME}" in dockerfile
    assert f'= "{PINNED_CHROME_VERSION}"' in dockerfile
    assert f'= "{PINNED_CHROME_PRODUCT_VERSION}"' in dockerfile


def _packages(*, version: str = PINNED_CHROME_VERSION) -> bytes:
    return (
        "Package: google-chrome-stable\n"
        "Architecture: amd64\n"
        f"Version: {version}\n"
        f"Filename: {PINNED_CHROME_FILENAME}\n"
        f"SHA256: {PINNED_CHROME_SHA256}\n"
        "Description: browser\n"
    ).encode()


def _metadata(
    *,
    version: str = PINNED_CHROME_VERSION,
    publication_date: str = "Wed, 19 Aug 2026 16:14:15 UTC",
) -> tuple[bytes, bytes]:
    packages_gzip = gzip.compress(_packages(version=version), mtime=0)
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
):
    payloads = {
        GOOGLE_SIGNING_KEY_URL: b"public-key",
        GOOGLE_INRELEASE_URL: inrelease,
        GOOGLE_PACKAGES_URL: packages_gzip,
    }

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
    inrelease, packages_gzip = _metadata(version="152.0.7977.65-1")

    with pytest.raises(ChromeReleaseError, match="no longer.*observed 152.0.7977.65-1"):
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
