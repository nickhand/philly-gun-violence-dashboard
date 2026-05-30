"""Pagination helpers."""

from collections.abc import Sequence
from typing import Literal, TypedDict


class PageData[T](TypedDict):
    """Pagination metadata with feature list."""

    type: Literal["FeatureCollection"]
    features: list[T]
    limit: int
    offset: int
    count: int
    total: int
    next_offset: int | None


def paginate_features[T](
    features: Sequence[T],
    *,
    limit: int,
    offset: int,
) -> tuple[list[T], int, int | None, int]:
    """Slice features with pagination metadata.

    Parameters
    ----------
    features : collections.abc.Sequence[T]
        Full list of features to paginate.
    limit : int
        Maximum number of features to return.
    offset : int
        Zero-based index of the first feature to return.

    Returns
    -------
    tuple[list[T], int, int | None, int]
        The page features, count, next offset, and total.
    """
    total = len(features)
    page_features = list(features[offset : offset + limit])
    count = len(page_features)
    next_offset = offset + count if offset + count < total else None
    return page_features, count, next_offset, total


def build_page[T](
    *,
    features: list[T],
    limit: int,
    offset: int,
    count: int,
    total: int,
    next_offset: int | None,
) -> PageData[T]:
    """Build a FeatureCollection page payload."""
    return {
        "type": "FeatureCollection",
        "features": features,
        "limit": limit,
        "offset": offset,
        "count": count,
        "total": total,
        "next_offset": next_offset,
    }
