#!/usr/bin/env python3
"""Render lock-controlled Chrome values into their checked-in consumers."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = REPOSITORY_ROOT / "packages/etl/chrome-lock.json"

DOCKERFILE_PATH = REPOSITORY_ROOT / "packages/etl/Dockerfile"
JUSTFILE_PATH = REPOSITORY_ROOT / "Justfile"
CONTAINER_DOC_PATH = REPOSITORY_ROOT / "packages/aws-batch-scraper/docs/container.md"
RELEASE_IMAGE_TEST_PATH = REPOSITORY_ROOT / "packages/aws-batch-scraper/tests/test_release_image.py"
ETL_README_PATH = REPOSITORY_ROOT / "packages/etl/README.md"

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
PRODUCT_VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+")
PACKAGE_VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-1")


class RenderChromeLockError(RuntimeError):
    """Raised when the lock or one of its generated consumers is invalid."""


@dataclass(frozen=True)
class ChromeLock:
    """Strictly validated Chrome release data used by checked-in consumers."""

    repository: str
    package_name: str
    architecture: str
    package_version: str
    product_version: str
    filename: str
    package_sha256: str
    executable_path: str
    executable_sha256: str

    @property
    def package_url(self) -> str:
        """Return the authenticated package's full download URL."""
        return f"{self.repository}/{self.filename}"


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON object keys instead of silently keeping the last value."""
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise RenderChromeLockError(f"Chrome lock contains duplicate key {key!r}")
        value[key] = item
    return value


def _read_utf8(path: Path, *, label: str) -> str:
    """Read one regular LF-terminated UTF-8 file."""
    if path.is_symlink() or not path.is_file():
        raise RenderChromeLockError(f"{label} must be a regular file: {path}")
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RenderChromeLockError(f"{label} is not valid UTF-8: {path}") from exc
    if "\r" in text:
        raise RenderChromeLockError(f"{label} must use LF line endings: {path}")
    if not text.endswith("\n"):
        raise RenderChromeLockError(f"{label} must end with a newline: {path}")
    return text


def _require_object(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise RenderChromeLockError(f"{label} must be a JSON object")
    return value


def _require_exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise RenderChromeLockError(
            f"{label} has invalid keys; missing={missing or 'none'}, extra={extra or 'none'}"
        )


def _require_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RenderChromeLockError(f"{label} must be a nonempty trimmed string")
    return value


def _require_exact_string(value: object, expected: str, *, label: str) -> str:
    observed = _require_string(value, label=label)
    if observed != expected:
        raise RenderChromeLockError(f"{label} must equal {expected!r}")
    return observed


def _require_pattern(value: object, pattern: re.Pattern[str], *, label: str) -> str:
    observed = _require_string(value, label=label)
    if pattern.fullmatch(observed) is None:
        raise RenderChromeLockError(f"{label} has an invalid format")
    return observed


def load_chrome_lock(path: Path = LOCK_PATH) -> ChromeLock:
    """Load and strictly validate the complete Chrome lock schema."""
    raw = _read_utf8(path, label="Chrome lock")
    try:
        decoded = json.loads(raw, object_pairs_hook=_unique_json_object)
    except JSONDecodeError as exc:
        raise RenderChromeLockError(f"Chrome lock is not valid JSON: {exc}") from exc

    root = _require_object(decoded, label="Chrome lock")
    _require_exact_keys(
        root,
        {"schema_version", "source", "package", "executable"},
        label="Chrome lock",
    )
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise RenderChromeLockError("Chrome lock schema_version must be the integer 1")

    source = _require_object(root["source"], label="Chrome lock source")
    _require_exact_keys(
        source,
        {"repository", "suite", "component"},
        label="Chrome lock source",
    )
    repository = _require_exact_string(
        source["repository"],
        "https://dl.google.com/linux/chrome/deb",
        label="Chrome lock source.repository",
    )
    _require_exact_string(source["suite"], "stable", label="Chrome lock source.suite")
    _require_exact_string(source["component"], "main", label="Chrome lock source.component")

    package = _require_object(root["package"], label="Chrome lock package")
    _require_exact_keys(
        package,
        {"name", "architecture", "version", "product_version", "filename", "sha256"},
        label="Chrome lock package",
    )
    package_name = _require_exact_string(
        package["name"], "google-chrome-stable", label="Chrome lock package.name"
    )
    architecture = _require_exact_string(
        package["architecture"], "amd64", label="Chrome lock package.architecture"
    )
    package_version = _require_pattern(
        package["version"], PACKAGE_VERSION_PATTERN, label="Chrome lock package.version"
    )
    product_version = _require_pattern(
        package["product_version"],
        PRODUCT_VERSION_PATTERN,
        label="Chrome lock package.product_version",
    )
    if package_version != f"{product_version}-1":
        raise RenderChromeLockError(
            "Chrome lock package.version must equal package.product_version plus '-1'"
        )
    filename = _require_string(package["filename"], label="Chrome lock package.filename")
    expected_filename = (
        f"pool/main/g/{package_name}/{package_name}_{package_version}_{architecture}.deb"
    )
    if filename != expected_filename:
        raise RenderChromeLockError(
            f"Chrome lock package.filename must equal {expected_filename!r}"
        )
    package_sha256 = _require_pattern(
        package["sha256"], SHA256_PATTERN, label="Chrome lock package.sha256"
    )

    executable = _require_object(root["executable"], label="Chrome lock executable")
    _require_exact_keys(executable, {"path", "sha256"}, label="Chrome lock executable")
    executable_path = _require_exact_string(
        executable["path"],
        "/opt/google/chrome/chrome",
        label="Chrome lock executable.path",
    )
    executable_sha256 = _require_pattern(
        executable["sha256"], SHA256_PATTERN, label="Chrome lock executable.sha256"
    )

    return ChromeLock(
        repository=repository,
        package_name=package_name,
        architecture=architecture,
        package_version=package_version,
        product_version=product_version,
        filename=filename,
        package_sha256=package_sha256,
        executable_path=executable_path,
        executable_sha256=executable_sha256,
    )


BlockRenderer = Callable[[str, ChromeLock], str]


def _replace_marker_block(
    text: str,
    *,
    path: Path,
    marker: str,
    lock: ChromeLock,
    renderer: BlockRenderer,
    comment_prefix: str = "#",
    comment_suffix: str = "",
) -> str:
    """Replace exactly one explicitly marked generated block."""
    begin = f"{comment_prefix} BEGIN GENERATED: {marker}{comment_suffix}"
    end = f"{comment_prefix} END GENERATED: {marker}{comment_suffix}"
    pattern = re.compile(rf"(?ms)^{re.escape(begin)}\n(?P<body>.*?)^{re.escape(end)}$")
    matches = list(pattern.finditer(text))
    if len(matches) != 1 or text.count(begin) != 1 or text.count(end) != 1:
        raise RenderChromeLockError(
            f"{path.relative_to(REPOSITORY_ROOT)} must contain exactly one {marker!r} marker block"
        )
    match = matches[0]
    rendered_body = renderer(match.group("body"), lock)
    if not rendered_body.endswith("\n"):
        raise AssertionError(f"Renderer for {marker} omitted its trailing newline")
    return text[: match.start()] + begin + "\n" + rendered_body + end + text[match.end() :]


def _replace_counted_pattern(
    text: str,
    *,
    path: Path,
    label: str,
    pattern: re.Pattern[str],
    value: str,
    expected_count: int,
) -> str:
    """Replace one narrowly scoped captured value and reject structural drift."""

    def replace(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{value}{match.group('suffix')}"

    rendered, count = pattern.subn(replace, text)
    if count != expected_count:
        raise RenderChromeLockError(
            f"{path.relative_to(REPOSITORY_ROOT)} expected {expected_count} {label} "
            f"pattern(s), found {count}"
        )
    return rendered


def _docker_package_block(_current: str, lock: ChromeLock) -> str:
    return (
        f"ADD --checksum=sha256:{lock.package_sha256} \\\n"
        f"    {lock.package_url} \\\n"
        "    /tmp/google-chrome-stable.deb\n"
    )


def _render_release_contract_block(current: str, lock: ChromeLock) -> str:
    """Update only the Chrome fields in a two-line Just release contract."""
    lines = current.splitlines()
    if len(lines) != 2:
        raise RenderChromeLockError("Chrome release-contract marker must contain exactly two lines")

    requirement_match = re.fullmatch(
        r'aws_batch_scraper_required_sbom_packages := "(?P<value>[^"\n]+)"',
        lines[0],
    )
    digest_match = re.fullmatch(
        r'aws_batch_scraper_chrome_executable_sha256 := "sha256:(?P<digest>[0-9a-f]{64})"',
        lines[1],
    )
    if requirement_match is None or digest_match is None:
        raise RenderChromeLockError("Chrome release-contract marker has an invalid assignment")

    requirements = requirement_match.group("value").split(",")
    chrome_indexes = [
        index
        for index, requirement in enumerate(requirements)
        if requirement.startswith("deb:google-chrome-stable=")
    ]
    if (
        chrome_indexes != [1]
        or PACKAGE_VERSION_PATTERN.fullmatch(
            requirements[1].removeprefix("deb:google-chrome-stable=")
        )
        is None
    ):
        raise RenderChromeLockError(
            "Chrome release-contract requirements must contain one Chrome deb in position 2"
        )
    requirements[1] = f"deb:{lock.package_name}={lock.package_version}"
    return (
        f'aws_batch_scraper_required_sbom_packages := "{",".join(requirements)}"\n'
        "aws_batch_scraper_chrome_executable_sha256 := "
        f'"sha256:{lock.executable_sha256}"\n'
    )


def _render_test_constants(_current: str, lock: ChromeLock) -> str:
    return (
        f'CHROME_PACKAGE_VERSION = "{lock.package_version}"\n'
        f'CHROME_VERSION = "{lock.product_version}"\n'
        f'CHROME_SHA256 = "sha256:{lock.executable_sha256}"\n'
    )


def _render_readme_product(_current: str, lock: ChromeLock) -> str:
    return (
        "It full-upgrades that snapshot before installing Ubuntu's native Python\n"
        "(3.13 or newer) and a checksum-pinned Google Chrome "
        f"{lock.product_version} package.\n"
    )


def _render_dockerfile(text: str, lock: ChromeLock) -> str:
    rendered = _replace_marker_block(
        text,
        path=DOCKERFILE_PATH,
        marker="chrome-lock-package",
        lock=lock,
        renderer=_docker_package_block,
    )
    rendered = _replace_counted_pattern(
        rendered,
        path=DOCKERFILE_PATH,
        label="Chrome package-version assertion",
        pattern=re.compile(
            r'(?m)^(?P<prefix>        = ")'
            r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-1"
            r'(?P<suffix>" \\)$'
        ),
        value=lock.package_version,
        expected_count=1,
    )
    return _replace_counted_pattern(
        rendered,
        path=DOCKERFILE_PATH,
        label="Chrome product-version assertion",
        pattern=re.compile(
            r'(?m)^(?P<prefix>    && test "\$\(google-chrome --product-version\)" = ")'
            r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+"
            r'(?P<suffix>" \\)$'
        ),
        value=lock.product_version,
        expected_count=2,
    )


def render_consumers(lock: ChromeLock) -> dict[Path, tuple[str, str]]:
    """Return every consumer's current and lock-rendered content without writing."""
    current = {
        path: _read_utf8(path, label="Chrome lock consumer")
        for path in (
            DOCKERFILE_PATH,
            JUSTFILE_PATH,
            CONTAINER_DOC_PATH,
            RELEASE_IMAGE_TEST_PATH,
            ETL_README_PATH,
        )
    }

    rendered: dict[Path, str] = {}
    rendered[DOCKERFILE_PATH] = _render_dockerfile(current[DOCKERFILE_PATH], lock)
    rendered[JUSTFILE_PATH] = _replace_marker_block(
        current[JUSTFILE_PATH],
        path=JUSTFILE_PATH,
        marker="chrome-lock-release-contract",
        lock=lock,
        renderer=_render_release_contract_block,
    )
    rendered[CONTAINER_DOC_PATH] = _replace_marker_block(
        current[CONTAINER_DOC_PATH],
        path=CONTAINER_DOC_PATH,
        marker="chrome-lock-release-contract",
        lock=lock,
        renderer=_render_release_contract_block,
    )
    rendered[RELEASE_IMAGE_TEST_PATH] = _replace_marker_block(
        current[RELEASE_IMAGE_TEST_PATH],
        path=RELEASE_IMAGE_TEST_PATH,
        marker="chrome-lock-test-constants",
        lock=lock,
        renderer=_render_test_constants,
    )
    rendered[ETL_README_PATH] = _replace_marker_block(
        current[ETL_README_PATH],
        path=ETL_README_PATH,
        marker="chrome-lock-product-version",
        lock=lock,
        renderer=_render_readme_product,
        comment_prefix="<!--",
        comment_suffix=" -->",
    )

    return {path: (current[path], rendered[path]) for path in current}


def _diff(path: Path, current: str, rendered: str) -> str:
    relative = path.relative_to(REPOSITORY_ROOT).as_posix()
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="show drift without writing files")
    mode.add_argument("--write", action="store_true", help="rewrite every drifted consumer")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        lock = load_chrome_lock()
        consumers = render_consumers(lock)
    except (OSError, RenderChromeLockError) as exc:
        print(f"Chrome lock rendering failed: {exc}", file=sys.stderr)
        return 2

    changed = [
        (path, current, rendered)
        for path, (current, rendered) in consumers.items()
        if current != rendered
    ]
    if args.check:
        if not changed:
            print("Chrome lock consumers are current.")
            return 0
        for path, current, rendered in changed:
            print(_diff(path, current, rendered), end="", file=sys.stderr)
        print(
            "Chrome lock consumers are stale; run "
            "`python3 packages/etl/scripts/render_chrome_lock.py --write`.",
            file=sys.stderr,
        )
        return 1

    for path, _current, rendered in changed:
        path.write_bytes(rendered.encode("utf-8"))
        print(f"Updated {path.relative_to(REPOSITORY_ROOT).as_posix()}")
    if not changed:
        print("Chrome lock consumers already match the lock.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
