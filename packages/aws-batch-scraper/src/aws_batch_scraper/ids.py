"""Run ID generation."""

import uuid
from datetime import UTC, datetime


def make_run_id() -> str:
    """Create a sortable run ID like 2026-05-19T143022Z-a3f1."""
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    return f"{ts}-{uuid.uuid4().hex[:4]}"
