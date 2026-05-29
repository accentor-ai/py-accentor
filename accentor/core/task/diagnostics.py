from __future__ import annotations

"""Canonical task diagnostic records."""

import math
import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

JsonValue = None | bool | int | float | str | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]

_VALID_SEVERITIES = frozenset({"debug", "info", "warning", "error", "critical"})


def _normalize_json_value(value: Any) -> JsonValue:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("diagnostic details must not contain non-finite floats")
        return value
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("diagnostic detail keys must be strings")
            normalized[key] = _normalize_json_value(item)
        return MappingProxyType(normalized)
    if isinstance(value, (list, tuple)):
        return tuple(_normalize_json_value(item) for item in value)
    raise TypeError(f"diagnostic details must be JSON-compatible, got {type(value).__name__}")


def _normalize_details(details: Mapping[str, Any] | None) -> Mapping[str, JsonValue]:
    if details is None:
        return MappingProxyType({})
    if not isinstance(details, Mapping):
        raise TypeError("diagnostic details must be a mapping")
    return _normalize_json_value(details)  # type: ignore[return-value]


def _plain_json_value(value: JsonValue) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """User-facing task diagnostic with stable attribute access."""

    code: str
    message: str
    severity: str = "error"
    source: str | None = None
    hint: str | None = None
    details: Mapping[str, JsonValue] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("diagnostic code is required")
        if not self.message:
            raise ValueError("diagnostic message is required")
        if self.severity not in _VALID_SEVERITIES:
            allowed = ", ".join(sorted(_VALID_SEVERITIES))
            raise ValueError(f"diagnostic severity must be one of: {allowed}")
        object.__setattr__(self, "details", _normalize_details(self.details))

    @classmethod
    def debug(
        cls,
        code: str,
        message: str,
        *,
        source: str | None = None,
        hint: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "Diagnostic":
        return cls(code=code, message=message, severity="debug", source=source, hint=hint, details=details)

    @classmethod
    def info(
        cls,
        code: str,
        message: str,
        *,
        source: str | None = None,
        hint: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "Diagnostic":
        return cls(code=code, message=message, severity="info", source=source, hint=hint, details=details)

    @classmethod
    def warning(
        cls,
        code: str,
        message: str,
        *,
        source: str | None = None,
        hint: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "Diagnostic":
        return cls(code=code, message=message, severity="warning", source=source, hint=hint, details=details)

    @classmethod
    def error(
        cls,
        code: str,
        message: str,
        *,
        source: str | None = None,
        hint: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "Diagnostic":
        return cls(code=code, message=message, severity="error", source=source, hint=hint, details=details)

    @classmethod
    def critical(
        cls,
        code: str,
        message: str,
        *,
        source: str | None = None,
        hint: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "Diagnostic":
        return cls(code=code, message=message, severity="critical", source=source, hint=hint, details=details)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "source": self.source,
            "hint": self.hint,
            "details": _plain_json_value(self.details),
        }


__all__ = ["Diagnostic"]
