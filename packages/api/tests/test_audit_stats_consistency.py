"""Tests for optimization-safe release audit invariants."""

import pytest

from scripts.audit_stats_consistency import AuditError, _require


def test_require_raises_explicit_audit_error() -> None:
    """Release checks must not disappear when Python assertions are optimized out."""
    with pytest.raises(AuditError, match="contract failed"):
        _require(False, "contract failed")


def test_require_accepts_truthy_contract() -> None:
    """Satisfied release contracts return normally."""
    _require(True, "not raised")
