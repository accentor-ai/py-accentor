"""Text validators."""

from __future__ import annotations

import json
import re
from typing import Any

from accentor.evaluate.validation.base import (
    _MISSING,
    ValidationContext,
    ValidationResult,
    Validator,
    ensure_context,
    get_path,
    stringify_text,
)


def _text_candidate(candidate: Any, context: ValidationContext | None) -> str:
    ctx = ensure_context(candidate, context)
    if ctx.raw_text is not None:
        return ctx.raw_text
    return stringify_text(ctx.raw_candidate if candidate is None else candidate)


def _parsed_candidate(candidate: Any, context: ValidationContext | None) -> Any:
    ctx = ensure_context(candidate, context)
    if ctx.parsed_available:
        return ctx.parsed_candidate
    raw = candidate if candidate is not None else ctx.raw_candidate
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def _field_or_text(
    candidate: Any,
    context: ValidationContext | None,
    field: str | None,
    *,
    validator: Any,
) -> tuple[str | None, ValidationResult | None]:
    if field is None:
        return _text_candidate(candidate, context), None

    data = _parsed_candidate(candidate, context)
    value = get_path(data, field)
    if value is _MISSING:
        return None, ValidationResult.failure(
            f"Missing JSON field: {field}",
            validator=validator,
            code="validation.json_field_missing",
            metadata={"field": field},
        )
    return stringify_text(value), None


class NoMarkdownFences(Validator):
    """Reject Markdown code fences in raw output."""

    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        text = _text_candidate(candidate, context)
        if "```" in text:
            return ValidationResult.failure(
                "Output must not contain Markdown code fences.",
                validator=self,
                code="validation.markdown_fence",
            )
        return ValidationResult.success(validator=self.__class__.__name__, criteria=self.criteria)


class TitleMaxWords(Validator):
    """Require a text field or candidate to stay within a word limit."""

    def __init__(self, *, max_words: int, field: str | None = None, description: str | None = None) -> None:
        self.field = field
        self.max_words = max_words
        self.description = description

    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        text, failure = _field_or_text(candidate, context, self.field, validator=self)
        if failure is not None:
            return failure
        assert text is not None
        count = len(text.split())
        if count > self.max_words:
            return ValidationResult.failure(
                f"Title has {count} words; expected at most {self.max_words}.",
                validator=self,
                code="validation.word_count_exceeded",
                metadata={"field": self.field, "actual": count, "max_words": self.max_words},
            )
        return ValidationResult.success(
            validator=self.__class__.__name__,
            criteria=self.criteria,
            metadata={"field": self.field, "word_count": count},
        )


class ContainsPhrase(Validator):
    """Require text or a text field to contain a phrase."""

    def __init__(
        self,
        phrase: str | None = None,
        *,
        field: str | None = None,
        case_sensitive: bool = True,
        description: str | None = None,
    ) -> None:
        if phrase is None:
            raise ValueError("ContainsPhrase requires phrase")
        self.field = field
        self.phrase = phrase
        self.case_sensitive = case_sensitive
        self.description = description

    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        text, failure = _field_or_text(candidate, context, self.field, validator=self)
        if failure is not None:
            return failure
        assert text is not None
        haystack = text if self.case_sensitive else text.lower()
        needle = self.phrase if self.case_sensitive else self.phrase.lower()
        if needle not in haystack:
            return ValidationResult.failure(
                f"Text does not contain required phrase: {self.phrase}",
                validator=self,
                code="validation.phrase_missing",
                metadata={"field": self.field, "phrase": self.phrase},
            )
        return ValidationResult.success(
            validator=self.__class__.__name__,
            criteria=self.criteria,
            metadata={"field": self.field, "phrase": self.phrase},
        )


class ExactPhraseCount(Validator):
    """Require a phrase to appear exactly ``count`` times."""

    def __init__(
        self,
        phrase: str,
        *,
        count: int,
        field: str | None = None,
        case_sensitive: bool = True,
        description: str | None = None,
    ) -> None:
        self.field = field
        self.phrase = phrase
        self.count = count
        self.case_sensitive = case_sensitive
        self.description = description

    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        text, failure = _field_or_text(candidate, context, self.field, validator=self)
        if failure is not None:
            return failure
        assert text is not None
        haystack = text if self.case_sensitive else text.lower()
        needle = self.phrase if self.case_sensitive else self.phrase.lower()
        actual = haystack.count(needle)
        if actual != self.count:
            return ValidationResult.failure(
                f"Phrase {self.phrase!r} appeared {actual} times; expected {self.count}.",
                validator=self,
                code="validation.phrase_count_mismatch",
                metadata={"field": self.field, "phrase": self.phrase, "actual": actual, "expected": self.count},
            )
        return ValidationResult.success(
            validator=self.__class__.__name__,
            criteria=self.criteria,
            metadata={"field": self.field, "phrase": self.phrase, "count": actual},
        )


class ForbiddenPattern(Validator):
    """Reject text matching a regular expression pattern."""

    def __init__(
        self,
        pattern: str,
        label: str | None = None,
        *,
        field: str | None = None,
        flags: int = 0,
        description: str | None = None,
    ) -> None:
        self.pattern = pattern
        self.label = label or pattern
        self.field = field
        self.flags = flags
        self.description = description
        self._compiled = re.compile(pattern, flags)

    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        text, failure = _field_or_text(candidate, context, self.field, validator=self)
        if failure is not None:
            return failure
        assert text is not None
        if self._compiled.search(text):
            return ValidationResult.failure(
                f"Text contains forbidden pattern: {self.label}",
                validator=self,
                code="validation.forbidden_pattern",
                metadata={"field": self.field, "label": self.label, "pattern": self.pattern},
            )
        return ValidationResult.success(
            validator=self.__class__.__name__,
            criteria=self.criteria,
            metadata={"field": self.field, "label": self.label},
        )


class ExactFinalMessage(Validator):
    """Require final raw output text to equal an expected message."""

    def __init__(self, expected: str, description: str | None = None) -> None:
        self.expected = expected
        self.description = description

    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        actual = _text_candidate(candidate, context).strip()
        if actual != self.expected:
            return ValidationResult.failure(
                "Final message did not match expected text.",
                validator=self,
                code="validation.final_message_mismatch",
                metadata={"expected": self.expected, "actual": actual},
            )
        return ValidationResult.success(validator=self.__class__.__name__, criteria=self.criteria)


__all__ = [
    "ContainsPhrase",
    "ExactFinalMessage",
    "ExactPhraseCount",
    "ForbiddenPattern",
    "NoMarkdownFences",
    "TitleMaxWords",
]
