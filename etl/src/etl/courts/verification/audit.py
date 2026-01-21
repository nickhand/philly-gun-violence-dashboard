"""Audit logging for UJS CaseSearch scraper verification.

Provides structured NDJSON audit logging for both per-attempt and
per-incident-number (final) records.
"""

import gzip
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from loguru import logger

from etl.courts.verification.classifier import Classification, ClassificationResult
from etl.courts.verification.shard import AuditContext


@dataclass
class AttemptAuditRow:
    """Audit record for a single scrape attempt.

    One record is written per attempt (including retries).

    Attributes
    ----------
    run_id : str
        Run identifier (shared across shards).
    shard_id : int
        Shard index (0-based).
    shard_count : int
        Total number of shards.
    task_id : str | None
        Task identifier (Fargate ARN or hostname).
    incident_number_raw : str
        Original incident number as provided.
    incident_number_normalized : str
        Normalized incident number.
    attempt_index : int
        Attempt number (1-based).
    attempt_timestamp_start : str
        ISO timestamp when attempt started.
    attempt_timestamp_end : str
        ISO timestamp when attempt ended.
    elapsed_ms : int
        Duration of the attempt in milliseconds.
    classification : str
        Classification bucket (e.g., HAS_RESULTS, ZERO_RESULTS).
    subreason : str | None
        Additional classification detail.
    final_url : str
        Final URL after navigation.
    row_count : int | None
        Number of result rows (for HAS_RESULTS).
    marker_hits : dict[str, bool] | None
        Detection markers that triggered.
    status_histogram : dict[int, int] | None
        HTTP status code counts.
    requestfailed_count : int
        Number of failed requests.
    will_retry : bool
        Whether a retry will be attempted.
    sleep_s : float | None
        Planned sleep before next attempt (if retrying).
    screenshot_path : str | None
        Path to screenshot (if captured).
    error_message : str | None
        Error message (if exception occurred).
    """

    run_id: str
    shard_id: int
    shard_count: int
    task_id: str | None
    incident_number_raw: str
    incident_number_normalized: str
    attempt_index: int
    attempt_timestamp_start: str
    attempt_timestamp_end: str
    elapsed_ms: int
    classification: str
    subreason: str | None
    final_url: str
    row_count: int | None
    marker_hits: dict[str, bool] | None
    status_histogram: dict[int, int] | None
    requestfailed_count: int
    will_retry: bool
    sleep_s: float | None
    screenshot_path: str | None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)


@dataclass
class FinalAuditRow:
    """Audit record for the final outcome of an incident number.

    One record per incident number per shard run.

    Attributes
    ----------
    run_id : str
        Run identifier.
    shard_id : int
        Shard index.
    shard_count : int
        Total number of shards.
    task_id : str | None
        Task identifier.
    incident_number_raw : str
        Original incident number.
    incident_number_normalized : str
        Normalized incident number.
    final_classification : str
        Final classification bucket.
    attempt_count_total : int
        Total number of attempts made.
    first_success_attempt_index : int | None
        First attempt that returned HAS_RESULTS/ZERO_RESULTS (if any).
    last_attempt_classification : str
        Classification of the last attempt.
    last_attempt_subreason : str | None
        Subreason of the last attempt.
    final_url : str
        Final URL from last attempt.
    row_count : int | None
        Number of result rows (if HAS_RESULTS).
    marker_hits : dict[str, bool] | None
        Marker hits from last attempt.
    status_histogram_agg : dict[int, int] | None
        Aggregated status histogram across all attempts.
    screenshots : list[str]
        Paths to all captured screenshots.
    total_elapsed_ms : int
        Total time across all attempts.
    timestamp_start : str
        ISO timestamp when first attempt started.
    timestamp_end : str
        ISO timestamp when last attempt ended.
    """

    run_id: str
    shard_id: int
    shard_count: int
    task_id: str | None
    incident_number_raw: str
    incident_number_normalized: str
    final_classification: str
    attempt_count_total: int
    first_success_attempt_index: int | None
    last_attempt_classification: str
    last_attempt_subreason: str | None
    final_url: str
    row_count: int | None
    marker_hits: dict[str, bool] | None
    status_histogram_agg: dict[int, int] | None
    screenshots: list[str]
    total_elapsed_ms: int
    timestamp_start: str
    timestamp_end: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)


class AuditWriter:
    """NDJSON audit log writer with optional gzip compression.

    Supports append-only writing for robustness during long runs.
    Supports S3 destinations by writing to local temp directory then uploading on close.

    Attributes
    ----------
    base_path : str
        Base directory for shard (e.g., 'shards/shard-00' or 's3://bucket/path/shard-00').
    run_id : str
        Run identifier.
    shard_id : int
        Shard index.
    compress : bool
        Whether to gzip output files.
    """

    def __init__(
        self,
        base_path: str,
        run_id: str,
        shard_id: int,
        compress: bool = True,
    ) -> None:
        """Initialize the audit writer.

        Parameters
        ----------
        base_path : str
            Base directory for shard (e.g., 'shards/shard-00' or 's3://bucket/path').
            Audit files will be written to {base_path}/audit/.
            If base_path is an S3 URI, files are written locally then uploaded on close.
        run_id : str
            Run identifier.
        shard_id : int
            Shard index.
        compress : bool
            Whether to gzip output files.
        """
        self.base_path = base_path
        self.run_id = run_id
        self.shard_id = shard_id
        self.compress = compress

        # Check if destination is S3
        self._is_s3 = base_path.startswith("s3://")
        self._s3_destination: str | None = None

        if self._is_s3:
            # Write to temp directory, upload on close
            import tempfile

            self._temp_dir = tempfile.mkdtemp(prefix=f"audit_shard{shard_id}_")
            self.output_dir = Path(self._temp_dir)
            self._s3_destination = base_path.rstrip("/") + "/audit"
        else:
            # Write directly to local path
            self._temp_dir = None
            self.output_dir = Path(base_path) / "audit"

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # File paths: audit/attempts.ndjson.gz, audit/final.ndjson.gz
        ext = ".ndjson.gz" if compress else ".ndjson"
        self.attempts_path = self.output_dir / f"attempts{ext}"
        self.final_path = self.output_dir / f"final{ext}"
        self.screenshots_dir = self.output_dir / "screenshots"

        # File handles (lazy opened)
        self._attempts_file: TextIO | gzip.GzipFile | None = None
        self._final_file: TextIO | gzip.GzipFile | None = None

        logger.info(f"Audit writer initialized: {self.output_dir}")

    def _open_file(self, path: Path) -> TextIO | gzip.GzipFile:
        """Open a file for append-mode writing.

        Parameters
        ----------
        path : Path
            File path.

        Returns
        -------
        TextIO | gzip.GzipFile
            Opened file handle.
        """
        if self.compress:
            # Use 'ab' for append binary, then wrap with gzip
            return gzip.open(path, "at", encoding="utf-8")
        else:
            return open(path, "a", encoding="utf-8")

    def write_attempt(self, row: AttemptAuditRow) -> None:
        """Write an attempt audit record.

        Parameters
        ----------
        row : AttemptAuditRow
            The attempt record to write.
        """
        if self._attempts_file is None:
            self._attempts_file = self._open_file(self.attempts_path)

        line = json.dumps(row.to_dict(), separators=(",", ":")) + "\n"
        self._attempts_file.write(line)
        self._attempts_file.flush()

    def write_final(self, row: FinalAuditRow) -> None:
        """Write a final audit record.

        Parameters
        ----------
        row : FinalAuditRow
            The final record to write.
        """
        if self._final_file is None:
            self._final_file = self._open_file(self.final_path)

        line = json.dumps(row.to_dict(), separators=(",", ":")) + "\n"
        self._final_file.write(line)
        self._final_file.flush()

    def get_screenshot_path(self, incident_number: str, attempt_index: int) -> Path:
        """Get the path for a screenshot file.

        Parameters
        ----------
        incident_number : str
            Normalized incident number.
        attempt_index : int
            Attempt number (1-based).

        Returns
        -------
        Path
            Full path for the screenshot file.
        """
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        return self.screenshots_dir / f"{incident_number}_attempt{attempt_index}.png"

    def get_error_screenshot_path(self, input_value: str) -> Path:
        """Get the path for an error screenshot file.

        Parameters
        ----------
        input_value : str
            Input value that caused the error.

        Returns
        -------
        Path
            Full path for the error screenshot file.
        """
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        # Sanitize input value for filename
        safe_name = input_value.replace("/", "_").replace("\\", "_")
        return self.screenshots_dir / f"{safe_name}_error.png"

    def local_to_s3_path(self, local_path: str | Path) -> str:
        """Convert a local path to the corresponding S3 URI.

        Parameters
        ----------
        local_path : str | Path
            Local file path (within output_dir).

        Returns
        -------
        str
            S3 URI for the file (or the local path if not S3 destination).
        """
        if not self._is_s3 or not self._s3_destination:
            return str(local_path)

        local_path = Path(local_path)
        try:
            rel_path = local_path.relative_to(self.output_dir)
            return f"{self._s3_destination}/{rel_path}"
        except ValueError:
            # Path is not relative to output_dir
            return str(local_path)

    def close(self) -> None:
        """Close all open file handles and upload to S3 if needed."""
        if self._attempts_file is not None:
            self._attempts_file.close()
            self._attempts_file = None
        if self._final_file is not None:
            self._final_file.close()
            self._final_file = None

        # Upload to S3 if destination was S3
        if self._is_s3 and self._s3_destination:
            self._upload_to_s3()

        # Clean up temp directory
        if self._temp_dir:
            import shutil

            try:
                shutil.rmtree(self._temp_dir)
            except Exception as e:
                logger.warning(f"Failed to clean up temp dir {self._temp_dir}: {e}")

    def _upload_to_s3(self) -> None:
        """Upload local audit files to S3 destination (recursively)."""
        from dashboard_utils.aws import make_s3_client, parse_s3_uri

        assert self._s3_destination is not None

        bucket, prefix = parse_s3_uri(self._s3_destination)
        s3 = make_s3_client()

        # Recursively upload all files in output_dir (including screenshots/)
        for file_path in self.output_dir.rglob("*"):
            if file_path.is_file():
                # Compute relative path from output_dir
                rel_path = file_path.relative_to(self.output_dir)
                key = f"{prefix}/{rel_path}"
                logger.debug(f"Uploading audit file to s3://{bucket}/{key}")
                s3.upload_file(str(file_path), bucket, key)

        logger.info(
            f"Uploaded audit files to {self._s3_destination} "
            f"(attempts: {self.attempts_path.exists()}, final: {self.final_path.exists()})"
        )

    def __enter__(self) -> "AuditWriter":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


@dataclass
class AttemptTracker:
    """Track attempts for a single incident number to build final audit row.

    Attributes
    ----------
    audit_context : AuditContext
        Shard context for metadata.
    incident_number_raw : str
        Original incident number.
    incident_number_normalized : str
        Normalized incident number.
    attempts : list[AttemptAuditRow]
        All attempt records.
    """

    audit_context: AuditContext
    incident_number_raw: str
    incident_number_normalized: str
    attempts: list[AttemptAuditRow] = field(default_factory=list)
    _start_time: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def add_attempt(
        self,
        result: ClassificationResult,
        attempt_index: int,
        timestamp_start: str,
        timestamp_end: str,
        will_retry: bool,
        sleep_s: float | None,
        screenshot_path: str | None,
    ) -> AttemptAuditRow:
        """Record an attempt and return the audit row.

        Parameters
        ----------
        result : ClassificationResult
            Classification result for the attempt.
        attempt_index : int
            Attempt number (1-based).
        timestamp_start : str
            ISO timestamp when attempt started.
        timestamp_end : str
            ISO timestamp when attempt ended.
        will_retry : bool
            Whether a retry will be attempted.
        sleep_s : float | None
            Planned sleep before retry.
        screenshot_path : str | None
            Path to screenshot if captured.

        Returns
        -------
        AttemptAuditRow
            The attempt audit record.
        """
        row = AttemptAuditRow(
            run_id=self.audit_context.run_id,
            shard_id=self.audit_context.shard_id,
            shard_count=self.audit_context.shard_count,
            task_id=self.audit_context.task_id,
            incident_number_raw=self.incident_number_raw,
            incident_number_normalized=self.incident_number_normalized,
            attempt_index=attempt_index,
            attempt_timestamp_start=timestamp_start,
            attempt_timestamp_end=timestamp_end,
            elapsed_ms=result.elapsed_ms,
            classification=result.classification.value,
            subreason=result.subreason,
            final_url=result.final_url,
            row_count=result.row_count,
            marker_hits=result.marker_hits,
            status_histogram=result.status_histogram,
            requestfailed_count=result.requestfailed_count,
            will_retry=will_retry,
            sleep_s=sleep_s,
            screenshot_path=screenshot_path,
            error_message=result.error_message,
        )
        self.attempts.append(row)
        return row

    def build_final_row(self) -> FinalAuditRow:
        """Build the final audit row from all attempts.

        Returns
        -------
        FinalAuditRow
            Final audit record summarizing all attempts.
        """
        if not self.attempts:
            raise ValueError("No attempts recorded")

        # Determine final classification
        # Priority: HAS_RESULTS > ZERO_RESULTS > last attempt
        final_classification: str | None = None
        first_success_index: int | None = None

        for attempt in self.attempts:
            if attempt.classification == Classification.HAS_RESULTS.value:
                final_classification = Classification.HAS_RESULTS.value
                if first_success_index is None:
                    first_success_index = attempt.attempt_index
                break
            elif attempt.classification == Classification.ZERO_RESULTS.value:
                if final_classification != Classification.HAS_RESULTS.value:
                    final_classification = Classification.ZERO_RESULTS.value
                    if first_success_index is None:
                        first_success_index = attempt.attempt_index

        if final_classification is None:
            final_classification = self.attempts[-1].classification

        # Aggregate status histograms
        status_histogram_agg: dict[int, int] = {}
        for attempt in self.attempts:
            if attempt.status_histogram:
                for code, count in attempt.status_histogram.items():
                    status_histogram_agg[code] = status_histogram_agg.get(code, 0) + count

        # Collect screenshots
        screenshots = [a.screenshot_path for a in self.attempts if a.screenshot_path is not None]

        # Calculate total elapsed time
        total_elapsed_ms = sum(a.elapsed_ms for a in self.attempts)

        # Get last attempt for final details
        last = self.attempts[-1]

        # Determine row count (from first HAS_RESULTS if any)
        row_count: int | None = None
        for attempt in self.attempts:
            if (
                attempt.classification == Classification.HAS_RESULTS.value
                and attempt.row_count is not None
            ):
                row_count = attempt.row_count
                break

        return FinalAuditRow(
            run_id=self.audit_context.run_id,
            shard_id=self.audit_context.shard_id,
            shard_count=self.audit_context.shard_count,
            task_id=self.audit_context.task_id,
            incident_number_raw=self.incident_number_raw,
            incident_number_normalized=self.incident_number_normalized,
            final_classification=final_classification,
            attempt_count_total=len(self.attempts),
            first_success_attempt_index=first_success_index,
            last_attempt_classification=last.classification,
            last_attempt_subreason=last.subreason,
            final_url=last.final_url,
            row_count=row_count,
            marker_hits=last.marker_hits,
            status_histogram_agg=status_histogram_agg if status_histogram_agg else None,
            screenshots=screenshots,
            total_elapsed_ms=total_elapsed_ms,
            timestamp_start=self._start_time,
            timestamp_end=last.attempt_timestamp_end,
        )


def create_audit_writer(
    audit_context: AuditContext,
    base_path: str | None = None,
    compress: bool = True,
) -> AuditWriter:
    """Create an audit writer for a shard.

    Parameters
    ----------
    audit_context : AuditContext
        Shard context with run/shard metadata.
    base_path : str | None
        Base path for audit files. Defaults to AUDIT_OUTPUT_DIR env var or 'artifacts'.
    compress : bool
        Whether to gzip output files.

    Returns
    -------
    AuditWriter
        Configured audit writer.
    """
    if base_path is None:
        base_path = os.getenv("AUDIT_OUTPUT_DIR", "artifacts")

    return AuditWriter(
        base_path=base_path,
        run_id=audit_context.run_id,
        shard_id=audit_context.shard_id,
        compress=compress,
    )
