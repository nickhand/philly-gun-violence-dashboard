"""Homicide statistics ETL."""

from .pipeline import update_homicide_totals

__all__ = ["update_homicide_totals"]
