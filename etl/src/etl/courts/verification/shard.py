"""Shard assignment and context for parallel UJS scraping.

Provides deterministic shard assignment using stable hashing (SHA1),
and context management for tracking run/shard metadata.
"""

import hashlib
import os
import socket
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


def normalize_incident_number(raw_value: str) -> str:
    """Normalize an incident number for consistent hashing.

    Strips whitespace, converts to uppercase, and handles the 12->10 digit format.

    Parameters
    ----------
    raw_value : str
        Raw incident number string.

    Returns
    -------
    str
        Normalized incident number.
    """
    value = str(raw_value).strip().upper()

    # Handle 12-digit format (strip first 2 chars)
    if len(value) == 12 and value[:2].isdigit():
        value = value[2:]

    return value


def assign_shard(normalized_incident_number: str, shard_count: int) -> int:
    """Deterministically assign an incident number to a shard.

    Uses SHA1 hashing for stable, reproducible shard assignment.
    Do NOT use Python's built-in hash() as it's not stable across processes.

    Parameters
    ----------
    normalized_incident_number : str
        Normalized incident number (use normalize_incident_number first).
    shard_count : int
        Total number of shards.

    Returns
    -------
    int
        Shard index (0 to shard_count - 1).

    Raises
    ------
    ValueError
        If shard_count < 1.
    """
    if shard_count < 1:
        raise ValueError("shard_count must be >= 1")

    if shard_count == 1:
        return 0

    # Use SHA1 for stable hashing
    hash_bytes = hashlib.sha1(normalized_incident_number.encode("utf-8")).digest()
    # Convert first 8 bytes to int for modulo
    hash_int = int.from_bytes(hash_bytes[:8], byteorder="big")
    return hash_int % shard_count


@dataclass(frozen=True)
class AuditContext:
    """Context for a shard worker in a parallel scrape run.

    Attributes
    ----------
    run_id : str
        Unique identifier for this run (shared across all shards).
    shard_id : int
        This shard's index (0-based).
    shard_count : int
        Total number of shards in the run.
    task_id : str | None
        Optional task identifier (e.g., Fargate task ARN or container hostname).
    created_at : str
        ISO timestamp when context was created.
    """

    run_id: str
    shard_id: int
    shard_count: int
    task_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        """Validate shard configuration."""
        if self.shard_id < 0:
            raise ValueError(f"shard_id must be >= 0, got {self.shard_id}")
        if self.shard_count < 1:
            raise ValueError(f"shard_count must be >= 1, got {self.shard_count}")
        if self.shard_id >= self.shard_count:
            raise ValueError(
                f"shard_id ({self.shard_id}) must be < shard_count ({self.shard_count})"
            )

    def is_my_shard(self, normalized_incident_number: str) -> bool:
        """Check if an incident number belongs to this shard.

        Parameters
        ----------
        normalized_incident_number : str
            Normalized incident number.

        Returns
        -------
        bool
            True if the incident number should be processed by this shard.
        """
        return assign_shard(normalized_incident_number, self.shard_count) == self.shard_id

    def filter_my_items(self, items: list[str]) -> list[str]:
        """Filter a list of incident numbers to only those in this shard.

        Parameters
        ----------
        items : list[str]
            List of raw or normalized incident numbers.

        Returns
        -------
        list[str]
            Incident numbers that belong to this shard.
        """
        return [
            item for item in items if self.is_my_shard(normalize_incident_number(item))
        ]

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dictionary."""
        return {
            "run_id": self.run_id,
            "shard_id": self.shard_id,
            "shard_count": self.shard_count,
            "task_id": self.task_id,
            "created_at": self.created_at,
        }


def _get_task_id() -> str | None:
    """Get task identifier from environment.

    Checks for Fargate task ARN, then falls back to hostname.

    Returns
    -------
    str | None
        Task identifier or None if not available.
    """
    # Check for ECS/Fargate task ARN
    task_arn = os.getenv("AWS_EXECUTION_ENV")
    if task_arn:
        # In ECS, we can try to get the task ARN from metadata
        ecs_container_metadata = os.getenv("ECS_CONTAINER_METADATA_URI_V4")
        if ecs_container_metadata:
            try:
                import httpx

                resp = httpx.get(f"{ecs_container_metadata}/task", timeout=2.0)
                if resp.status_code == 200:
                    task_data = resp.json()
                    return task_data.get("TaskARN")
            except Exception:
                pass

    # Fall back to hostname
    try:
        return socket.gethostname()
    except Exception:
        return None


def _generate_run_id() -> str:
    """Generate a unique run ID.

    Format: YYYYMMDD-HHMMSS-{short_uuid}

    Returns
    -------
    str
        Unique run identifier.
    """
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{timestamp}-{short_uuid}"


def get_audit_context(
    *,
    run_id: str | None = None,
    shard_id: int | None = None,
    shard_count: int | None = None,
    task_id: str | None = None,
) -> AuditContext:
    """Create a shard context from environment variables or explicit values.

    Environment Variables
    ---------------------
    RUN_ID : str
        Unique run identifier (auto-generated if not set).
    SHARD_ID : int
        This shard's index, 0-based (default: 0).
    SHARD_COUNT : int
        Total number of shards (default: 1).
    TASK_ID : str
        Task identifier (auto-detected if not set).

    Parameters
    ----------
    run_id : str | None
        Override for RUN_ID env var.
    shard_id : int | None
        Override for SHARD_ID env var.
    shard_count : int | None
        Override for SHARD_COUNT env var.
    task_id : str | None
        Override for TASK_ID env var.

    Returns
    -------
    AuditContext
        Configured shard context.
    """
    # Resolve values with env var fallbacks
    resolved_run_id = run_id or os.getenv("RUN_ID") or _generate_run_id()

    resolved_shard_id = shard_id
    if resolved_shard_id is None:
        env_shard_id = os.getenv("SHARD_ID")
        resolved_shard_id = int(env_shard_id) if env_shard_id else 0

    resolved_shard_count = shard_count
    if resolved_shard_count is None:
        env_shard_count = os.getenv("SHARD_COUNT")
        resolved_shard_count = int(env_shard_count) if env_shard_count else 1

    resolved_task_id = task_id or os.getenv("TASK_ID") or _get_task_id()

    return AuditContext(
        run_id=resolved_run_id,
        shard_id=resolved_shard_id,
        shard_count=resolved_shard_count,
        task_id=resolved_task_id,
    )


def get_shard_artifact_path(
    base_path: str,
    run_id: str,
    shard_id: int,
    filename: str,
) -> str:
    """Build artifact path for a shard.

    Parameters
    ----------
    base_path : str
        Base directory or S3 prefix.
    run_id : str
        Run identifier.
    shard_id : int
        Shard index.
    filename : str
        Artifact filename.

    Returns
    -------
    str
        Full path: {base_path}/{run_id}/shard={shard_id}/{filename}
    """
    # Handle both S3 and local paths
    if base_path.endswith("/"):
        base_path = base_path[:-1]
    return f"{base_path}/{run_id}/shard={shard_id}/{filename}"
