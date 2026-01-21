"""UJS CaseSearch scraper verification modules.

This package provides verification-grade audit logging, response classification,
and tenacity-aware retry observability for the UJS portal scraper.

The verification functionality is integrated into the main UJSPortalScraper
via the `verify=True` flag. These modules provide the underlying utilities.
"""

from etl.courts.verification.audit import (
    AttemptAuditRow,
    AttemptTracker,
    AuditWriter,
    FinalAuditRow,
    create_audit_writer,
)
from etl.courts.verification.classifier import (
    Classification,
    ClassificationResult,
    classify_case_search,
    classify_from_exception,
)
from etl.courts.verification.config import ScraperConfig, get_scraper_config
from etl.courts.verification.diagnose import run as diagnose_run
from etl.courts.verification.net_observer import NetworkObserver
from etl.courts.verification.shard import AuditContext, assign_shard, get_audit_context

__all__ = [
    # Audit
    "AttemptAuditRow",
    "AttemptTracker",
    "AuditWriter",
    "FinalAuditRow",
    "create_audit_writer",
    # Classification
    "Classification",
    "ClassificationResult",
    "classify_case_search",
    "classify_from_exception",
    # Config
    "ScraperConfig",
    "get_scraper_config",
    # Diagnostics
    "diagnose_run",
    # Network observer
    "NetworkObserver",
    # Sharding
    "AuditContext",
    "assign_shard",
    "get_audit_context",
]
