"""Tests for pagination invariants."""

import pytest

from app.utils.pagination import paginate_features


def test_paginate_features_requires_forward_progress() -> None:
    """A non-empty result cannot point clients back to the same offset."""
    with pytest.raises(ValueError, match="at least 1"):
        paginate_features([1, 2, 3], limit=0, offset=0)


def test_paginate_features_rejects_negative_offset() -> None:
    """Negative offsets are never meaningful collection positions."""
    with pytest.raises(ValueError, match="non-negative"):
        paginate_features([1, 2, 3], limit=1, offset=-1)


def test_paginate_features_advances_or_finishes() -> None:
    """Every valid page either advances or reports terminal completion."""
    page, count, next_offset, total = paginate_features([1, 2, 3], limit=2, offset=0)
    assert (page, count, next_offset, total) == ([1, 2], 2, 2, 3)

    page, count, next_offset, total = paginate_features([1, 2, 3], limit=2, offset=2)
    assert (page, count, next_offset, total) == ([3], 1, None, 3)
