"""Unsupported Pydantic validator stubs for v1.

This module intentionally does not import pydantic.
"""

from __future__ import annotations

from accentor.evaluate.validation.base import UnsupportedValidator


class PydanticValidator(UnsupportedValidator):
    """Base placeholder for Pydantic validators not implemented in v1."""

    feature = "Pydantic model validation"


class PydanticModelValidator(PydanticValidator):
    feature = "Pydantic model validation"


class ModelValidator(PydanticValidator):
    feature = "Pydantic model validation"


PydanticModel = PydanticModelValidator


__all__ = [
    "ModelValidator",
    "PydanticModel",
    "PydanticModelValidator",
    "PydanticValidator",
]
