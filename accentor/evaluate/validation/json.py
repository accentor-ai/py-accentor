"""JSON validators."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from accentor.evaluate.validation.base import (
    _MISSING,
    UnsupportedValidator,
    ValidationContext,
    ValidationResult,
    Validator,
    ensure_context,
    get_path,
)


def _coerce_json_candidate(
    candidate: Any,
    context: ValidationContext | None,
    *,
    validator: Any,
) -> tuple[Any, ValidationResult | None]:
    ctx = ensure_context(candidate, context)
    if ctx.parsed_available:
        return ctx.parsed_candidate, None

    raw = candidate if candidate is not None else ctx.raw_candidate
    if isinstance(raw, str):
        try:
            return json.loads(raw), None
        except json.JSONDecodeError as exc:
            return None, ValidationResult.failure(
                f"Candidate is not valid JSON: {exc.msg}",
                validator=validator,
                code="validation.json_invalid",
                metadata={"line": exc.lineno, "column": exc.colno},
                parsed_json_required=True,
            )

    if isinstance(raw, bytes):
        try:
            return json.loads(raw.decode("utf-8")), None
        except UnicodeDecodeError as exc:
            return None, ValidationResult.failure(
                "Candidate bytes are not valid UTF-8.",
                validator=validator,
                code="validation.json_invalid",
                metadata={"error": str(exc)},
                parsed_json_required=True,
            )
        except json.JSONDecodeError as exc:
            return None, ValidationResult.failure(
                f"Candidate is not valid JSON: {exc.msg}",
                validator=validator,
                code="validation.json_invalid",
                metadata={"line": exc.lineno, "column": exc.colno},
                parsed_json_required=True,
            )

    if isinstance(raw, (Mapping, list, int, float, bool)) or raw is None:
        return raw, None

    return None, ValidationResult.failure(
        f"Candidate is not JSON-compatible: {type(raw).__name__}",
        validator=validator,
        code="validation.json_invalid",
        metadata={"type": type(raw).__name__},
        parsed_json_required=True,
    )


def _key_tuple(keys: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    return tuple(str(key) for key in keys or ())


class JsonRequired(Validator):
    """Require valid JSON, optionally with required root object keys."""

    def __init__(
        self,
        *,
        keys: list[str] | tuple[str, ...] | None = None,
        description: str | None = None,
    ) -> None:
        self.keys = _key_tuple(keys)
        self.description = description

    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        data, failure = _coerce_json_candidate(candidate, context, validator=self)
        if failure is not None:
            return failure
        if self.keys:
            if not isinstance(data, Mapping):
                return ValidationResult.failure(
                    "JSON root must be an object with required keys: " + ", ".join(self.keys),
                    validator=self,
                    code="validation.json_not_object",
                    metadata={"keys": self.keys},
                    parsed_json_required=True,
                )
            missing = tuple(key for key in self.keys if key not in data)
            if missing:
                return ValidationResult.failure(
                    "Missing required JSON key(s): " + ", ".join(missing),
                    validator=self,
                    code="validation.required_keys_missing",
                    metadata={"missing_keys": list(missing), "keys": self.keys},
                    parsed_json_required=True,
                )
        return ValidationResult.success(
            validator=self.__class__.__name__,
            criteria=self.criteria,
            metadata={"keys": self.keys},
            parsed_json_required=True,
        )


class RequiredKeys(Validator):
    """Require object keys, or validate a JSON file when ``path`` is provided."""

    def __init__(
        self,
        path: str | os.PathLike[str] | list[str] | tuple[str, ...] | None = None,
        *,
        keys: list[str] | tuple[str, ...] | None = None,
        description: str | None = None,
    ) -> None:
        if keys is None and path is not None and not isinstance(path, (str, os.PathLike)):
            self.path = None
            self.keys = _key_tuple(path)
        else:
            self.path = path if keys is not None else None
            self.keys = _key_tuple(keys)
        self.description = description

    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        if self.path is not None:
            from accentor.evaluate.validation.files import FileRequiredKeys

            return FileRequiredKeys(self.path, keys=self.keys, description=self.description).validate(
                candidate,
                context,
            )

        data, failure = _coerce_json_candidate(candidate, context, validator=self)
        if failure is not None:
            return failure
        if not isinstance(data, Mapping):
            return ValidationResult.failure(
                "JSON root must be an object with required keys: " + ", ".join(self.keys),
                validator=self,
                code="validation.json_not_object",
                metadata={"keys": self.keys},
                parsed_json_required=True,
            )
        missing = tuple(key for key in self.keys if key not in data)
        if missing:
            return ValidationResult.failure(
                "Missing required JSON key(s): " + ", ".join(missing),
                validator=self,
                code="validation.required_keys_missing",
                metadata={"missing_keys": list(missing), "keys": self.keys},
                parsed_json_required=True,
            )
        return ValidationResult.success(
            validator=self.__class__.__name__,
            criteria=self.criteria,
            metadata={"keys": self.keys},
            parsed_json_required=True,
        )


class JsonFieldEquals(Validator):
    """Require a JSON field path to equal an expected value."""

    def __init__(
        self,
        field: str,
        expected: Any = _MISSING,
        *,
        value: Any = _MISSING,
        description: str | None = None,
    ) -> None:
        self.field = field
        self.value = value if expected is _MISSING and value is not _MISSING else expected
        self.description = description

    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        data, failure = _coerce_json_candidate(candidate, context, validator=self)
        if failure is not None:
            return failure
        actual = get_path(data, self.field)
        if actual is _MISSING:
            return ValidationResult.failure(
                f"Missing JSON field: {self.field}",
                validator=self,
                code="validation.json_field_missing",
                metadata={"field": self.field},
                parsed_json_required=True,
            )
        if actual != self.value:
            return ValidationResult.failure(
                f"JSON field {self.field!r} must equal {self.value!r}; got {actual!r}.",
                validator=self,
                code="validation.json_field_mismatch",
                metadata={"field": self.field, "expected": self.value, "actual": actual},
                parsed_json_required=True,
            )
        return ValidationResult.success(
            validator=self.__class__.__name__,
            criteria=self.criteria,
            metadata={"field": self.field, "expected": self.value},
            parsed_json_required=True,
        )


class ArrayLength(Validator):
    """Require a JSON array field or root array to satisfy length constraints."""

    def __init__(
        self,
        *,
        field: str | None = None,
        exactly: int | None = None,
        min_length: int | None = None,
        max_length: int | None = None,
        description: str | None = None,
    ) -> None:
        if exactly is None and min_length is None and max_length is None:
            raise ValueError("ArrayLength requires exactly, min_length, or max_length")
        self.field = field
        self.exactly = exactly
        self.min_length = min_length
        self.max_length = max_length
        self.description = description

    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        data, failure = _coerce_json_candidate(candidate, context, validator=self)
        if failure is not None:
            return failure

        value = get_path(data, self.field)
        if value is _MISSING:
            return ValidationResult.failure(
                f"Missing JSON field: {self.field}",
                validator=self,
                code="validation.json_field_missing",
                metadata={"field": self.field},
                parsed_json_required=True,
            )
        if not isinstance(value, list):
            return ValidationResult.failure(
                "JSON value must be an array.",
                validator=self,
                code="validation.array_required",
                metadata={"field": self.field, "actual_type": type(value).__name__},
                parsed_json_required=True,
            )

        length = len(value)
        if self.exactly is not None and length != self.exactly:
            return ValidationResult.failure(
                f"Array length was {length}; expected {self.exactly}.",
                validator=self,
                code="validation.array_length_mismatch",
                metadata={"field": self.field, "actual": length, "expected": self.exactly},
                parsed_json_required=True,
            )
        if self.min_length is not None and length < self.min_length:
            return ValidationResult.failure(
                f"Array length was {length}; expected at least {self.min_length}.",
                validator=self,
                code="validation.array_length_mismatch",
                metadata={"field": self.field, "actual": length, "min_length": self.min_length},
                parsed_json_required=True,
            )
        if self.max_length is not None and length > self.max_length:
            return ValidationResult.failure(
                f"Array length was {length}; expected at most {self.max_length}.",
                validator=self,
                code="validation.array_length_mismatch",
                metadata={"field": self.field, "actual": length, "max_length": self.max_length},
                parsed_json_required=True,
            )
        return ValidationResult.success(
            validator=self.__class__.__name__,
            criteria=self.criteria,
            metadata={"field": self.field, "length": length},
            parsed_json_required=True,
        )


class JsonSchema(UnsupportedValidator):
    """Unsupported v1 JSON Schema validator placeholder."""

    feature = "JSON Schema validation"


__all__ = ["ArrayLength", "JsonFieldEquals", "JsonRequired", "JsonSchema", "RequiredKeys"]
