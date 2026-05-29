from __future__ import annotations

"""Records shared by extraction and validation boundaries."""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from accentor.core.task.diagnostics import Diagnostic


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("extraction values must not contain non-finite floats")
        return value
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("extraction mapping keys must be strings")
            normalized[key] = _json_ready(item)
        return normalized
    if isinstance(value, tuple) and hasattr(value, "_asdict"):
        return _json_ready(value._asdict())
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=repr)]
    raise TypeError(f"extraction values must be JSON-compatible, got {type(value).__name__}")


def _normalize_metadata(metadata: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if metadata is None:
        return MappingProxyType({})
    if not isinstance(metadata, Mapping):
        raise TypeError("metadata must be a mapping")
    normalized = _json_ready(metadata)
    if not isinstance(normalized, dict):
        raise TypeError("metadata must serialize to a JSON object")
    return MappingProxyType(normalized)


def _normalize_diagnostics(items: Sequence[Diagnostic | Mapping[str, Any]] | None) -> tuple[Diagnostic, ...]:
    if items is None:
        return ()
    normalized: list[Diagnostic] = []
    for item in items:
        if isinstance(item, Diagnostic):
            normalized.append(item)
        elif isinstance(item, Mapping):
            normalized.append(Diagnostic(**item))
        else:
            raise TypeError("diagnostics must contain Diagnostic objects or diagnostic mappings")
    return tuple(normalized)


def _context_path(value: str | os.PathLike[str] | None) -> Path | None:
    if value is None:
        return None
    return Path(value)


@dataclass(frozen=True, slots=True)
class JsonParseFailure:
    """Structured JSON parse failure preserved as nonfatal extraction data."""

    message: str
    position: int | None = None
    line: int | None = None
    column: int | None = None
    source: str | None = None
    snippet: str | None = None
    code: str = "extraction.json_parse_failed"

    def __post_init__(self) -> None:
        if not self.message:
            raise ValueError("parse failure message is required")

    def to_diagnostic(self) -> Diagnostic:
        details = {
            "position": self.position,
            "line": self.line,
            "column": self.column,
            "snippet": self.snippet,
        }
        return Diagnostic.warning(
            self.code,
            self.message,
            source=self.source,
            details={key: value for key, value in details.items() if value is not None},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "position": self.position,
            "line": self.line,
            "column": self.column,
            "source": self.source,
            "snippet": self.snippet,
        }


def _normalize_parse_failures(
    items: Sequence[JsonParseFailure | Mapping[str, Any]] | None,
) -> tuple[JsonParseFailure, ...]:
    if items is None:
        return ()
    normalized: list[JsonParseFailure] = []
    for item in items:
        if isinstance(item, JsonParseFailure):
            normalized.append(item)
        elif isinstance(item, Mapping):
            normalized.append(JsonParseFailure(**item))
        else:
            raise TypeError("parse_failures must contain JsonParseFailure objects or mappings")
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class ExtractionContext:
    """Candidate context passed from extraction into validation."""

    raw: Any = None
    parsed: Any = None
    has_parsed: bool = False
    source: str | None = None
    artifact_root: Path | None = None
    artifact_store: Any = None
    path: Path | None = None
    artifact_name: str | None = None
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_root", _context_path(self.artifact_root))
        object.__setattr__(self, "path", _context_path(self.path))
        object.__setattr__(self, "diagnostics", _normalize_diagnostics(self.diagnostics))
        object.__setattr__(self, "metadata", _normalize_metadata(self.metadata))
        if not isinstance(self.has_parsed, bool):
            raise TypeError("has_parsed must be a bool")

    @property
    def raw_candidate(self) -> Any:
        return self.raw

    @property
    def raw_text(self) -> str | None:
        return self.raw if isinstance(self.raw, str) else None

    @property
    def parsed_candidate(self) -> Any:
        return self.parsed if self.has_parsed else None

    @property
    def parsed_json(self) -> Any:
        return self.parsed if self.has_parsed else None

    @property
    def parsed_available(self) -> bool:
        return self.has_parsed

    def candidate(self, *, prefer_parsed: bool = False) -> Any:
        if prefer_parsed and self.has_parsed:
            return self.parsed
        return self.raw

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": _json_ready(self.raw),
            "has_parsed": self.has_parsed,
            "parsed": _json_ready(self.parsed) if self.has_parsed else None,
            "source": self.source,
            "artifact_root": str(self.artifact_root) if self.artifact_root is not None else None,
            "path": str(self.path) if self.path is not None else None,
            "artifact_name": self.artifact_name,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "metadata": _json_ready(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Output of an extractor, preserving raw and parsed candidates."""

    raw: Any = None
    parsed: Any = None
    has_parsed: bool = False
    source: str | None = None
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    parse_failures: tuple[JsonParseFailure, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not isinstance(self.has_parsed, bool):
            raise TypeError("has_parsed must be a bool")
        object.__setattr__(self, "diagnostics", _normalize_diagnostics(self.diagnostics))
        object.__setattr__(self, "parse_failures", _normalize_parse_failures(self.parse_failures))
        object.__setattr__(self, "metadata", _normalize_metadata(self.metadata))

    @property
    def raw_candidate(self) -> Any:
        return self.raw

    @property
    def raw_text(self) -> str | None:
        return self.raw if isinstance(self.raw, str) else None

    @property
    def parsed_candidate(self) -> Any:
        return self.parsed if self.has_parsed else None

    @property
    def parsed_json(self) -> Any:
        return self.parsed if self.has_parsed else None

    @property
    def parsed_available(self) -> bool:
        return self.has_parsed

    def candidate(self, *, prefer_parsed: bool = False) -> Any:
        if prefer_parsed and self.has_parsed:
            return self.parsed
        return self.raw

    def to_context(
        self,
        *,
        artifact_root: str | os.PathLike[str] | None = None,
        artifact_store: Any = None,
        path: str | os.PathLike[str] | None = None,
        artifact_name: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExtractionContext:
        merged_metadata = dict(self.metadata)
        if metadata:
            merged_metadata.update(metadata)
        return ExtractionContext(
            raw=self.raw,
            parsed=self.parsed,
            has_parsed=self.has_parsed,
            source=self.source,
            artifact_root=_context_path(artifact_root),
            artifact_store=artifact_store,
            path=_context_path(path),
            artifact_name=artifact_name,
            diagnostics=self.diagnostics,
            metadata=merged_metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": _json_ready(self.raw),
            "has_parsed": self.has_parsed,
            "parsed": _json_ready(self.parsed) if self.has_parsed else None,
            "source": self.source,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "parse_failures": [failure.to_dict() for failure in self.parse_failures],
            "metadata": _json_ready(self.metadata),
        }


__all__ = [
    "ExtractionContext",
    "ExtractionResult",
    "JsonParseFailure",
]
