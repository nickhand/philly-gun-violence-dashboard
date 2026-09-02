#!/usr/bin/env python3
"""Validate or update the authoritative Chrome release lock."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence

from etl.chrome_release import (
    ChromeReleaseError,
    load_chrome_lock,
    update_chrome_lock,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate or update packages/etl/chrome-lock.json.",
    )
    parser.add_argument(
        "command",
        choices=("check", "status", "update"),
        help="check/status is offline and read-only; update authenticates Google and writes",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one explicit offline-check or networked-update operation."""
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "update":
            result = update_chrome_lock()
            disposition = "updated" if result.changed else "unchanged"
            print(f"Chrome lock {disposition}: {result.lock.package.version}")
        else:
            lock = load_chrome_lock()
            print(f"Chrome lock is valid: {lock.package.version}")
    except (ChromeReleaseError, OSError, subprocess.SubprocessError) as exc:
        print(f"Chrome lock {arguments.command} failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
