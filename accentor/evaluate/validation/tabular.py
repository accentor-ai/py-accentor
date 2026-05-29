"""Unsupported tabular validator stubs for v1."""

from __future__ import annotations

from accentor.evaluate.validation.base import UnsupportedValidator


class TabularValidator(UnsupportedValidator):
    """Base placeholder for tabular validators not implemented in v1."""

    feature = "tabular validation"


class PandasValidator(TabularValidator):
    feature = "pandas/tabular validation"


class RequiredColumns(TabularValidator):
    feature = "tabular required-column validation"


class ColumnValidator(TabularValidator):
    feature = "tabular column validation"


TableValidator = TabularValidator


__all__ = [
    "ColumnValidator",
    "PandasValidator",
    "RequiredColumns",
    "TableValidator",
    "TabularValidator",
]
