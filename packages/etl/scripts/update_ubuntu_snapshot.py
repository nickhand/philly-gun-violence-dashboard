#!/usr/bin/env python3
"""Refresh dated Ubuntu pins from authenticated archive indexes; never deploy."""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import re
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[3]
LOCK = Path("packages/etl/ubuntu-lock.json")
CONSUMERS = (
    Path("packages/etl/Dockerfile"),
    Path("Justfile"),
    Path(".github/workflows/scraper-image-quality.yml"),
    Path("packages/aws-batch-scraper/docs/container.md"),
)
ARCHIVE_SIGNER = "F6ECB3762474EDA9D21B7022871920D1991BC93C"


def download(url: str, limit: int) -> bytes:
    with urlopen(url, timeout=120) as response:
        data = response.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError("Ubuntu artifact is empty or exceeds its size limit")
    return data


def verify_index(release: str, path: str, data: bytes) -> None:
    section = release.split("\nSHA256:\n", 1)[1].split("\n\n", 1)[0]
    matches = re.findall(r"^ ([a-f0-9]{64})\s+(\d+) " + re.escape(path) + r"$", section, re.M)
    if len(matches) != 1 or matches[0] != (hashlib.sha256(data).hexdigest(), str(len(data))):
        raise ValueError("Ubuntu Packages index does not match signed SHA256 and size")


def package_records(data: bytes, names: set[str]):
    for paragraph in lzma.decompress(data, memlimit=256 * 1024 * 1024).decode().split("\n\n"):
        fields = dict(
            line.split(": ", 1)
            for line in paragraph.splitlines()
            if ": " in line and not line.startswith(" ")
        )
        if fields.get("Package") not in names or fields.get("Architecture") not in ("amd64", "all"):
            continue
        filename, digest = fields["Filename"], fields["SHA256"]
        if (
            not re.fullmatch(r"pool/[A-Za-z0-9_+./:~%-]+\.deb", filename)
            or ".." in filename
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
        ):
            raise ValueError("Unsafe Ubuntu package metadata")
        if not re.fullmatch(r"[0-9][A-Za-z0-9.+:~%-]*", fields["Version"]):
            raise ValueError("Unsafe Ubuntu version")
        yield (
            fields["Package"],
            {"version": fields["Version"], "filename": filename, "sha256": digest},
        )


def version_at_least(left: str, right: str) -> bool:
    result = subprocess.run(["dpkg", "--compare-versions", left, "ge", right], check=False)
    if result.returncode not in (0, 1):
        raise ValueError("dpkg version comparison failed")
    return result.returncode == 0


def resolve(old: dict[str, Any], snapshot: str, keyring: Path) -> dict[str, Any]:
    stamp = datetime.strptime(snapshot, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    if not datetime.now(UTC) - timedelta(days=7) <= stamp <= datetime.now(UTC):
        raise ValueError("New snapshot must be within the last seven days")
    if snapshot < old["snapshot"]:
        raise ValueError("Snapshot downgrade refused")
    base = f"https://snapshot.ubuntu.com/ubuntu/{snapshot}/"
    packages = {}
    with tempfile.TemporaryDirectory() as directory:
        for suite in ("resolute", "resolute-updates", "resolute-security"):
            signed = download(base + f"dists/{suite}/InRelease", 1024 * 1024)
            path = Path(directory, "InRelease")
            path.write_bytes(signed)
            verification = subprocess.run(
                ["gpgv", "--status-fd=1", "--keyring", str(keyring), str(path)],
                capture_output=True,
                text=True,
                check=True,
            )
            if not re.search(
                r"^\[GNUPG:\] VALIDSIG " + ARCHIVE_SIGNER + r" ", verification.stdout, re.M
            ):
                raise ValueError("Unexpected Ubuntu archive signer")
            release = signed.decode()
            for component in ("main", "universe"):
                index = f"{component}/binary-amd64/Packages.xz"
                data = download(base + f"dists/{suite}/{index}", 128 * 1024 * 1024)
                verify_index(release, index, data)
                for name, candidate in package_records(data, set(old["packages"])):
                    if name not in packages or version_at_least(
                        candidate["version"], packages[name]["version"]
                    ):
                        packages[name] = candidate
    if set(packages) != set(old["packages"]):
        raise ValueError("Signed indexes omitted a required package")
    for name, package in packages.items():
        if not version_at_least(package["version"], old["packages"][name]["version"]):
            raise ValueError(f"Package downgrade refused: {name}")
    bootstrap = {}
    for name in ("openssl", "ca-certificates"):
        package = packages[name]
        url = base + package["filename"]
        if hashlib.sha256(download(url, 32 * 1024 * 1024)).hexdigest() != package["sha256"]:
            raise ValueError("Bootstrap package differs from signed checksum")
        bootstrap[name] = {"url": url, "sha256": package["sha256"]}
    return {
        "schema_version": 1,
        "snapshot": snapshot,
        "packages": dict(sorted(packages.items())),
        "bootstrap": bootstrap,
    }


def render(text: str, old: dict[str, Any], new: dict[str, Any]) -> str:
    # Versions are replaced only in exact package assertions/SBOM requirements.
    text = text.replace(old["snapshot"], new["snapshot"])
    for name, package in old["packages"].items():
        before, after = package["version"], new["packages"][name]["version"]
        text = text.replace(f"deb:{name}={before}", f"deb:{name}={after}")
        pattern = (
            r"(dpkg-query --show --showformat='\$\{Version\}' "
            + re.escape(name)
            + r"\)\" \\\n        = \")"
            + re.escape(before)
            + '"'
        )
        text = re.sub(pattern, lambda m, after=after: m[1] + after + '"', text)
    for name, package in old["bootstrap"].items():
        text = text.replace(
            package["url"].replace(old["snapshot"], new["snapshot"]), new["bootstrap"][name]["url"]
        )
        text = text.replace(package["sha256"], new["bootstrap"][name]["sha256"])
    return text


def check(root: Path, lock: dict[str, Any]) -> None:
    source = (root / "packages/etl/Dockerfile").read_text()
    assert f"ARG UBUNTU_SNAPSHOT={lock['snapshot']}" in source
    assert f'test "$UBUNTU_SNAPSHOT" = "{lock["snapshot"]}"' in source
    for name, package in lock["packages"].items():
        assert re.search(
            r"dpkg-query --show --showformat='\$\{Version\}' "
            + re.escape(name)
            + r"\)\" \\\n        = \""
            + re.escape(package["version"])
            + '"',
            source,
        ), name
        if name not in ("openssl", "xz-utils"):
            for path in CONSUMERS[1:]:
                assert f"deb:{name}={package['version']}" in (root / path).read_text(), (name, path)
    for package in lock["bootstrap"].values():
        assert package["url"] in source and f"ADD --checksum=sha256:{package['sha256']}" in source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "update"))
    parser.add_argument(
        "--snapshot", default=(datetime.now(UTC) - timedelta(days=1)).strftime("%Y%m%dT000000Z")
    )
    parser.add_argument(
        "--keyring", type=Path, default=Path("/usr/share/keyrings/ubuntu-archive-keyring.gpg")
    )
    args = parser.parse_args()
    old = json.loads((ROOT / LOCK).read_text())
    check(ROOT, old)
    if args.command == "check":
        return
    new = resolve(old, args.snapshot, args.keyring)
    for path in CONSUMERS:
        target = ROOT / path
        target.write_text(render(target.read_text(), old, new))
    (ROOT / LOCK).write_text(json.dumps(new, indent=2) + "\n")
    check(ROOT, new)
    print(f"Ubuntu snapshot {new['snapshot']}; all required versions authenticated")


if __name__ == "__main__":
    main()
