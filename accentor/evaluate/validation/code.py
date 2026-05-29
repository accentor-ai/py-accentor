"""Unsupported code-quality validator stubs for v1."""

from __future__ import annotations

from accentor.evaluate.validation.base import UnsupportedValidator


class CodeValidator(UnsupportedValidator):
    """Base placeholder for code validators not implemented in v1."""

    feature = "code validation"


class RuffValidator(CodeValidator):
    feature = "Ruff code validation"


class MypyValidator(CodeValidator):
    feature = "mypy type validation"


class PytestValidator(CodeValidator):
    feature = "pytest validation"


Ruff = RuffValidator
Mypy = MypyValidator
Pytest = PytestValidator
PyTestValidator = PytestValidator


__all__ = [
    "CodeValidator",
    "Mypy",
    "MypyValidator",
    "PyTestValidator",
    "Pytest",
    "PytestValidator",
    "Ruff",
    "RuffValidator",
]
