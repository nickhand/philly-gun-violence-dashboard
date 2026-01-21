"""Diagnose audit output for quick issue identification.

This script analyzes merged audit files and outputs a summary of issues,
helping quickly identify problems with a scrape run.
"""

import gzip
import json
from collections import defaultdict
from pathlib import Path
from typing import Annotated, Any

import typer
from loguru import logger

from etl.courts.verification.classifier import Classification

app = typer.Typer(help="Diagnose audit output for quick issue identification.")

# Classification categories
SUCCESS_CLASSIFICATIONS = {Classification.HAS_RESULTS.value, Classification.ZERO_RESULTS.value}
FAILURE_CLASSIFICATIONS = {
    Classification.SOFT_BLOCKED.value,
    Classification.NETWORK_OR_SERVER_ERROR.value,
    Classification.UI_DRIFT_OR_UNKNOWN.value,
    Classification.REDIRECTED_OR_SESSION_LOST.value,
}


def read_ndjson(path: Path) -> list[dict]:
    """Read an NDJSON file (optionally gzipped)."""
    records = []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def find_audit_files(run_path: Path) -> tuple[Path | None, Path | None]:
    """Find merged audit files in a run directory.

    Parameters
    ----------
    run_path : Path
        Path to run directory or merged audit directory.

    Returns
    -------
    tuple[Path | None, Path | None]
        (final_merged_path, report_path) or (None, None) if not found.
    """
    # Check if it's already a merged/audit directory
    if run_path.name == "audit" and (run_path / "final_merged.ndjson.gz").exists():
        audit_dir = run_path
    # Check for merged/audit subdirectory
    elif (run_path / "merged" / "audit").exists():
        audit_dir = run_path / "merged" / "audit"
    # Check if final_merged exists directly
    elif (run_path / "final_merged.ndjson.gz").exists():
        audit_dir = run_path
    else:
        return None, None

    # Find the final merged file
    final_path = None
    for ext in [".ndjson.gz", ".ndjson"]:
        candidate = audit_dir / f"final_merged{ext}"
        if candidate.exists():
            final_path = candidate
            break

    # Find the report file
    report_path = None
    for name in ["report.json", "run_report.json"]:
        candidate = audit_dir / name
        if candidate.exists():
            report_path = candidate
            break

    return final_path, report_path


def analyze_records(records: list[dict]) -> dict[str, Any]:
    """Analyze audit records and produce diagnostic summary.

    Parameters
    ----------
    records : list[dict]
        List of final audit records.

    Returns
    -------
    dict[str, Any]
        Diagnostic summary.
    """
    total = len(records)
    if total == 0:
        return {"error": "No records found"}

    # Classification counts
    classification_counts: dict[str, int] = defaultdict(int)
    for r in records:
        classification_counts[r.get("final_classification", "UNKNOWN")] += 1

    # Success/failure counts
    success_count = sum(classification_counts.get(c, 0) for c in SUCCESS_CLASSIFICATIONS)
    failure_count = sum(classification_counts.get(c, 0) for c in FAILURE_CLASSIFICATIONS)

    # High retry incidents (>3 attempts)
    high_retry = [r for r in records if r.get("attempt_count_total", 1) > 3]

    # Incidents with 403/429 status codes
    rate_limited = []
    for r in records:
        histogram = r.get("status_histogram_agg", {})
        if histogram:
            # Handle both string and int keys
            has_403 = histogram.get(403, histogram.get("403", 0)) > 0
            has_429 = histogram.get(429, histogram.get("429", 0)) > 0
            if has_403 or has_429:
                rate_limited.append(r)

    # Group failures by subreason
    failure_subreasons: dict[str, list[str]] = defaultdict(list)
    for r in records:
        cls = r.get("final_classification", "")
        if cls in FAILURE_CLASSIFICATIONS:
            subreason = r.get("last_attempt_subreason", "unknown")
            incident = r.get("incident_number_normalized", "?")
            failure_subreasons[subreason].append(incident)

    # Per-shard stats
    shard_counts: dict[int, int] = defaultdict(int)
    shard_failures: dict[int, int] = defaultdict(int)
    for r in records:
        shard_id = r.get("shard_id", -1)
        shard_counts[shard_id] += 1
        if r.get("final_classification", "") in FAILURE_CLASSIFICATIONS:
            shard_failures[shard_id] += 1

    # Attempt count distribution
    attempt_counts = [r.get("attempt_count_total", 1) for r in records]
    avg_attempts = sum(attempt_counts) / len(attempt_counts)
    max_attempts = max(attempt_counts)

    # Attempt histogram with success/failure breakdown
    # Key: attempt count, Value: {"success": N, "failure": N, "incidents": [...]}
    attempt_histogram: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"success": 0, "failure": 0, "incidents": []}
    )
    for r in records:
        count = r.get("attempt_count_total", 1)
        cls = r.get("final_classification", "")
        incident = r.get("incident_number_raw", r.get("incident_number_normalized", "?"))
        attempt_histogram[count]["incidents"].append(incident)
        if cls in SUCCESS_CLASSIFICATIONS:
            attempt_histogram[count]["success"] += 1
        else:
            attempt_histogram[count]["failure"] += 1

    return {
        "total_records": total,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": success_count / total,
        "classification_counts": dict(classification_counts),
        "high_retry_count": len(high_retry),
        "high_retry_incidents": [r.get("incident_number_normalized") for r in high_retry[:10]],
        "rate_limited_count": len(rate_limited),
        "rate_limited_incidents": [r.get("incident_number_normalized") for r in rate_limited[:10]],
        "failure_subreasons": {k: len(v) for k, v in failure_subreasons.items()},
        "failure_samples": {k: v[:5] for k, v in failure_subreasons.items()},
        "shard_counts": dict(shard_counts),
        "shard_failure_rates": {
            s: shard_failures[s] / shard_counts[s] if shard_counts[s] > 0 else 0
            for s in shard_counts
        },
        "avg_attempts": avg_attempts,
        "max_attempts": max_attempts,
        "attempt_histogram": dict(attempt_histogram),
    }


def format_diagnosis(diagnosis: dict[str, Any], verbose: bool = False) -> str:
    """Format diagnosis as human-readable output.

    Parameters
    ----------
    diagnosis : dict[str, Any]
        Diagnostic summary from analyze_records.
    verbose : bool
        Include detailed incident lists.

    Returns
    -------
    str
        Formatted output.
    """
    lines = []
    lines.append("=" * 70)
    lines.append("SCRAPE RUN DIAGNOSIS")
    lines.append("=" * 70)
    lines.append("")

    # Overall stats
    total = diagnosis["total_records"]
    success = diagnosis["success_count"]
    failure = diagnosis["failure_count"]
    success_rate = diagnosis["success_rate"]

    lines.append("📊 OVERALL STATS")
    lines.append(f"   Total records:  {total:,}")
    lines.append(f"   Success:        {success:,} ({success_rate:.1%})")
    lines.append(f"   Failures:       {failure:,} ({1 - success_rate:.1%})")
    lines.append(f"   Avg attempts:   {diagnosis['avg_attempts']:.2f}")
    lines.append(f"   Max attempts:   {diagnosis['max_attempts']}")
    lines.append("")

    # Attempt histogram
    lines.append("🔄 ATTEMPT DISTRIBUTION")
    histogram = diagnosis["attempt_histogram"]
    # Calculate totals for bar scaling
    totals = {k: v["success"] + v["failure"] for k, v in histogram.items()}
    max_hist_count = max(totals.values()) if totals else 1
    for attempts in sorted(histogram.keys()):
        data = histogram[attempts]
        count = data["success"] + data["failure"]
        pct = count / total * 100
        bar_len = int(count / max_hist_count * 20)
        bar = "█" * bar_len
        # Show success/failure breakdown
        if data["failure"] > 0:
            breakdown = f" (✅{data['success']} ❌{data['failure']})"
        else:
            breakdown = ""
        lines.append(
            f"   {attempts} attempt{'s' if attempts != 1 else ' '}: {count:6,} ({pct:5.1f}%) {bar}{breakdown}"
        )
    lines.append("")

    # Classification breakdown
    lines.append("📋 CLASSIFICATION BREAKDOWN")
    for cls, count in sorted(diagnosis["classification_counts"].items(), key=lambda x: -x[1]):
        pct = count / total * 100
        bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
        emoji = "✅" if cls in SUCCESS_CLASSIFICATIONS else "❌"
        lines.append(f"   {emoji} {cls:30s} {count:6,} ({pct:5.1f}%) {bar[:20]}")
    lines.append("")

    # Issues section
    issues_found = False

    # Rate limiting
    if diagnosis["rate_limited_count"] > 0:
        issues_found = True
        lines.append("⚠️  RATE LIMITING DETECTED")
        lines.append(f"   {diagnosis['rate_limited_count']} incidents saw 403/429 responses")
        if verbose and diagnosis["rate_limited_incidents"]:
            lines.append(f"   Sample: {', '.join(diagnosis['rate_limited_incidents'][:5])}")
        lines.append("")

    # High retry counts
    if diagnosis["high_retry_count"] > 0:
        issues_found = True
        lines.append("⚠️  HIGH RETRY COUNTS (>3 attempts)")
        lines.append(f"   {diagnosis['high_retry_count']} incidents required >3 attempts")
        if verbose and diagnosis["high_retry_incidents"]:
            lines.append(f"   Sample: {', '.join(diagnosis['high_retry_incidents'][:5])}")
        lines.append("")

    # Failure subreasons
    if diagnosis["failure_subreasons"]:
        issues_found = True
        lines.append("❌ FAILURE REASONS")
        for reason, count in sorted(diagnosis["failure_subreasons"].items(), key=lambda x: -x[1]):
            lines.append(f"   {reason}: {count}")
            if verbose:
                samples = diagnosis["failure_samples"].get(reason, [])
                if samples:
                    lines.append(f"      └─ Sample: {', '.join(samples[:3])}")
        lines.append("")

    # Shard health
    shard_failure_rates = diagnosis["shard_failure_rates"]
    if shard_failure_rates:
        hot_shards = [s for s, rate in shard_failure_rates.items() if rate > 0.1]
        if hot_shards:
            issues_found = True
            lines.append("🔥 HOT SHARDS (>10% failure rate)")
            for s in sorted(hot_shards):
                rate = shard_failure_rates[s]
                count = diagnosis["shard_counts"][s]
                lines.append(f"   Shard {s}: {rate:.1%} failure rate ({count} records)")
            lines.append("")

    # Missing records (if --check-missing was used)
    if "missing_count" in diagnosis:
        expected = diagnosis["expected_count"]
        audited = diagnosis["audited_count"]
        missing = diagnosis["missing_count"]
        coverage = diagnosis["coverage_rate"]

        if missing > 0:
            issues_found = True
            lines.append("🚨 MISSING RECORDS (never attempted)")
            lines.append(f"   Expected:  {expected:,}")
            lines.append(f"   Audited:   {audited:,}")
            lines.append(f"   Missing:   {missing:,} ({1 - coverage:.1%})")
            if verbose and diagnosis["missing_incidents"]:
                lines.append(f"   Sample:    {', '.join(diagnosis['missing_incidents'][:10])}")
            lines.append("")
        else:
            lines.append(f"✅ ALL RECORDS ACCOUNTED FOR ({expected:,} expected)")
            lines.append("")

    if not issues_found:
        lines.append("✨ NO MAJOR ISSUES DETECTED")
        lines.append("")

    lines.append("=" * 70)

    return "\n".join(lines)


def find_input_file(run_path: Path) -> Path | None:
    """Find the merged input file in a run directory.

    Parameters
    ----------
    run_path : Path
        Path to run directory.

    Returns
    -------
    Path | None
        Path to portal_input.csv or None if not found.
    """
    # Check merged/portal_input.csv
    merged_input = run_path / "merged" / "portal_input.csv"
    if merged_input.exists():
        return merged_input

    # Check inputs/incident_numbers.csv (original input)
    original_input = run_path / "inputs" / "incident_numbers.csv"
    if original_input.exists():
        return original_input

    return None


def find_results_file(run_path: Path) -> Path | None:
    """Find the merged results file in a run directory.

    Parameters
    ----------
    run_path : Path
        Path to run directory.

    Returns
    -------
    Path | None
        Path to portal_results.json or None if not found.
    """
    # Check merged/portal_results.json
    merged_results = run_path / "merged" / "portal_results.json"
    if merged_results.exists():
        return merged_results

    return None


def find_shard_inputs(run_path: Path) -> tuple[dict[int, set[str]], dict[str, tuple[int, int]]]:
    """Find and read input.csv files from all shards.

    Parameters
    ----------
    run_path : Path
        Path to run directory.

    Returns
    -------
    tuple[dict[int, set[str]], dict[str, tuple[int, int, int]]]
        - Mapping of shard_id to set of DC keys assigned to that shard.
        - Mapping of dc_key to (shard_id, line_number, total_rows) for lookup.
    """
    import pandas as pd

    shard_inputs: dict[int, set[str]] = {}
    dc_key_locations: dict[str, tuple[int, int, int]] = {}  # dc_key -> (shard_id, line_num, total)

    # Look for shards/ directory
    shards_dir = run_path / "shards"
    if not shards_dir.exists():
        return shard_inputs, dc_key_locations

    # Find all shard-{NN} directories
    for shard_dir in sorted(shards_dir.glob("shard-*")):
        input_file = shard_dir / "input.csv"
        if input_file.exists():
            # Extract shard ID from directory name
            try:
                shard_id = int(shard_dir.name.split("-")[1])
            except (IndexError, ValueError):
                continue

            # Read the input file
            df = pd.read_csv(input_file, header=None, names=["dc_key"], dtype=str)
            shard_inputs[shard_id] = set(df["dc_key"].astype(str).values)
            total_rows = len(df)

            # Track line numbers (1-indexed) and total
            for line_num, dc_key in enumerate(df["dc_key"].astype(str).values, start=1):
                dc_key_locations[dc_key] = (shard_id, line_num, total_rows)

    return shard_inputs, dc_key_locations


@app.command()
def run(
    run_path: Annotated[
        str,
        typer.Argument(help="Path to run directory or merged audit directory."),
    ],
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show detailed incident lists."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON instead of formatted text."),
    ] = False,
    by_attempts: Annotated[
        int | None,
        typer.Option("--by-attempts", help="Output DC keys that took exactly N attempts."),
    ] = None,
    dc_key: Annotated[
        str | None,
        typer.Option("--dc-key", help="Look up audit record for a specific DC key."),
    ] = None,
    show_missing: Annotated[
        bool,
        typer.Option("--missing", help="Output DC keys that were never attempted."),
    ] = False,
) -> None:
    """Diagnose a scrape run and identify issues.

    Analyzes merged audit files and outputs:
    - Overall success/failure rates
    - Classification breakdown
    - Rate limiting detection
    - High retry incidents
    - Failure reasons
    - Shard health
    - Missing records (compared against input file)

    Use --by-attempts N to output DC keys that took exactly N attempts.
    Use --dc-key KEY to look up the full audit record for a specific incident.
    Use --missing to output DC keys that were never attempted.
    """
    path = Path(run_path)

    if not path.exists():
        logger.error(f"Path not found: {run_path}")
        raise typer.Exit(1)

    # Find audit files
    final_path, report_path = find_audit_files(path)

    if final_path is None:
        logger.error(f"No merged audit files found in {run_path}")
        logger.error("Expected: merged/audit/final_merged.ndjson.gz")
        raise typer.Exit(1)

    logger.info(f"Reading audit data from {final_path}")

    # Read and analyze
    records = read_ndjson(final_path)
    if not records:
        logger.error("No records found in audit file")
        raise typer.Exit(1)

    # Handle --dc-key: look up specific incident
    if dc_key is not None:
        matches = [
            r
            for r in records
            if r.get("incident_number_raw") == dc_key
            or r.get("incident_number_normalized") == dc_key
        ]
        if not matches:
            logger.error(f"No audit record found for DC key: {dc_key}")
            raise typer.Exit(1)

        logger.info(f"Found {len(matches)} audit record(s) for {dc_key}")

        # Also look up results if available
        results_path = find_results_file(path)
        results_data = None
        if results_path:
            with open(results_path) as f:
                all_results = json.load(f)
            # Results are keyed by dc_key
            results_data = all_results.get(dc_key)
            if results_data is not None:
                logger.info(f"Found {len(results_data)} court case(s) in results")
            else:
                logger.info("No results found for this DC key (may have been ZERO_RESULTS)")

        # Output combined info
        output = {
            "audit": matches[0] if len(matches) == 1 else matches,
            "results": results_data,
        }
        print(json.dumps(output, indent=2))
        return

    logger.info(f"Analyzing {len(records)} records...")
    diagnosis = analyze_records(records)
    logger.info(f"Max attempts observed: {diagnosis['max_attempts']}")

    # Check for missing records by comparing against input file
    input_path = find_input_file(path)
    if input_path:
        logger.info(f"Checking for missing records using {input_path}")
        import pandas as pd

        input_df = pd.read_csv(input_path, header=None, names=["dc_key"], dtype=str)
        expected = set(input_df["dc_key"].astype(str).values)

        # Get incident numbers from audit records (use raw, since input has raw)
        audited = set(str(r.get("incident_number_raw", "")) for r in records)

        missing = expected - audited
        diagnosis["expected_count"] = len(expected)
        diagnosis["audited_count"] = len(audited)
        diagnosis["missing_count"] = len(missing)
        diagnosis["missing_incidents"] = sorted(missing)[:50]  # First 50 for display
        diagnosis["missing_incidents_all"] = sorted(missing)  # All for --missing flag
        diagnosis["coverage_rate"] = len(audited) / len(expected) if expected else 1.0

        if missing:
            logger.warning(f"Found {len(missing)} missing records (not in audit)")

            # Check which shards the missing records were assigned to
            shard_inputs, dc_key_locations = find_shard_inputs(path)
            diagnosis["dc_key_locations"] = dc_key_locations  # Store for --missing output

            if shard_inputs:
                missing_by_shard: dict[int, list[str]] = {}
                missing_not_assigned: list[str] = []

                for dc_key in missing:
                    found_in_shard = None
                    for shard_id, shard_keys in shard_inputs.items():
                        if dc_key in shard_keys:
                            found_in_shard = shard_id
                            break

                    if found_in_shard is not None:
                        if found_in_shard not in missing_by_shard:
                            missing_by_shard[found_in_shard] = []
                        missing_by_shard[found_in_shard].append(dc_key)
                    else:
                        missing_not_assigned.append(dc_key)

                diagnosis["missing_by_shard"] = missing_by_shard
                diagnosis["missing_not_assigned"] = missing_not_assigned

                # Log summary
                if missing_by_shard:
                    logger.warning("Missing records were assigned to shards but not processed:")
                    for shard_id in sorted(missing_by_shard.keys()):
                        logger.warning(
                            f"  Shard {shard_id}: {len(missing_by_shard[shard_id])} records"
                        )
                if missing_not_assigned:
                    logger.error(
                        f"{len(missing_not_assigned)} records were never assigned to any shard!"
                    )
    else:
        logger.debug("No input file found - skipping missing records check")

    # Handle --missing: output DC keys that were never attempted
    if show_missing:
        if "missing_incidents_all" not in diagnosis:
            logger.error("Cannot find missing records - no input file found")
            logger.error("Expected: merged/portal_input.csv or inputs/incident_numbers.csv")
            raise typer.Exit(1)

        all_missing = diagnosis["missing_incidents_all"]
        if not all_missing:
            logger.info("No missing records found - all inputs were attempted")
            return

        logger.info(f"Found {len(all_missing)} missing records")

        # Get location lookup (dc_key -> (shard_id, line_num, total_rows))
        dc_key_locations = diagnosis.get("dc_key_locations", {})

        # Print header (right-aligned columns)
        print(f"{'shard':>5}  {'line':>11}  {'dc_key':>15}")

        # Output with shard and line info
        for incident in sorted(all_missing):
            location = dc_key_locations.get(incident)
            if location is not None:
                shard_id, line_num, total_rows = location
                line_str = f"{line_num}/{total_rows}"
                print(f"{shard_id:>5}  {line_str:>11}  {incident:>15}")
            else:
                print(f"{'?':>5}  {'?':>11}  {incident:>15}")
        return

    # Handle --by-attempts: output DC keys for specific attempt count
    if by_attempts is not None:
        histogram = diagnosis["attempt_histogram"]
        if by_attempts not in histogram:
            available = sorted(histogram.keys())
            logger.error(f"No records with {by_attempts} attempts. Available: {available}")
            raise typer.Exit(1)

        incidents = histogram[by_attempts]["incidents"]
        logger.info(f"Found {len(incidents)} records with {by_attempts} attempts")
        for incident in sorted(incidents):
            print(incident)
        return

    # Output
    if json_output:
        # Remove incidents lists for cleaner JSON output (can be large)
        diagnosis_clean = {
            k: (
                {kk: vv for kk, vv in v.items() if kk != "incidents"}
                if isinstance(v, dict) and "incidents" in v
                else v
            )
            for k, v in diagnosis.items()
        }
        if "attempt_histogram" in diagnosis_clean:
            diagnosis_clean["attempt_histogram"] = {
                k: {kk: vv for kk, vv in v.items() if kk != "incidents"}
                for k, v in diagnosis["attempt_histogram"].items()
            }
        print(json.dumps(diagnosis_clean, indent=2))
    else:
        print(format_diagnosis(diagnosis, verbose=verbose))


if __name__ == "__main__":
    app()
