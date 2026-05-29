from __future__ import annotations

"""Supported v1 validation APIs."""

from accentor.evaluate.validation.base import (
    ValidationContext,
    ValidationResult,
    Validator,
    all_of,
    any_of,
    criteria_description,
    not_,
    validator_slug,
)
from accentor.evaluate.validation.files import ExactMatch, FileRequiredKeys, RequiredFile
from accentor.evaluate.validation.json import ArrayLength, JsonFieldEquals, JsonRequired, RequiredKeys
from accentor.evaluate.validation.text import (
    ContainsPhrase,
    ExactFinalMessage,
    ExactPhraseCount,
    ForbiddenPattern,
    NoMarkdownFences,
    TitleMaxWords,
)


__all__ = [
    "ArrayLength",
    "ContainsPhrase",
    "ExactFinalMessage",
    "ExactMatch",
    "ExactPhraseCount",
    "FileRequiredKeys",
    "ForbiddenPattern",
    "JsonFieldEquals",
    "JsonRequired",
    "NoMarkdownFences",
    "RequiredFile",
    "RequiredKeys",
    "TitleMaxWords",
    "ValidationContext",
    "ValidationResult",
    "Validator",
    "all_of",
    "any_of",
    "criteria_description",
    "not_",
    "validator_slug",
]
