from __future__ import annotations

"""Canonical task result records and user-facing helpers."""

import json
import math
import os
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence, TypeVar

from accentor.core.task.diagnostics import Diagnostic
from accentor.core.task.events import TaskEvent
from accentor.record.artifacts.store import ArtifactRecord


T = TypeVar("T")
ArtifactReference = ArtifactRecord | Mapping[str, Any]


class TaskResultError(RuntimeError):
    """Raised when a caller asks to unwrap an unsuccessful task result."""

    def __init__(self, result: "TaskResult", message: str | None = None) -> None:
        self.result = result
        super().__init__(message or _failure_message(result))


def _failure_message(result: "TaskResult") -> str:
    if result.diagnostics:
        diagnostic = result.diagnostics[0]
        return f"TaskResult is not ok: [{diagnostic.code}] {diagnostic.message}"
    return "TaskResult is not ok"


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


def _normalize_events(items: Sequence[TaskEvent | Mapping[str, Any]] | None) -> tuple[TaskEvent, ...]:
    if items is None:
        return ()
    normalized: list[TaskEvent] = []
    for item in items:
        if isinstance(item, TaskEvent):
            normalized.append(item)
        elif isinstance(item, Mapping):
            normalized.append(TaskEvent(**item))
        else:
            raise TypeError("events must contain TaskEvent objects or event mappings")
    return tuple(normalized)


def _normalize_artifacts(items: Sequence[ArtifactReference] | None) -> tuple[ArtifactReference, ...]:
    if items is None:
        return ()
    normalized: list[ArtifactReference] = []
    for item in items:
        if isinstance(item, ArtifactRecord):
            normalized.append(item)
        elif isinstance(item, Mapping):
            artifact = _json_ready(item)
            if not isinstance(artifact, dict):
                raise TypeError("artifact mappings must serialize to JSON objects")
            normalized.append(MappingProxyType(artifact))
        else:
            raise TypeError("artifacts must contain ArtifactRecord objects or artifact mappings")
    return tuple(normalized)


def _artifact_to_dict(artifact: ArtifactReference) -> dict[str, Any]:
    if isinstance(artifact, ArtifactRecord):
        return artifact.to_dict()
    return _json_ready(artifact)


def _json_ready(value: Any) -> Any:
    """Convert record-shaped values into data accepted by ``json.dumps``."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("task result values must not contain non-finite floats")
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _json_ready(value.value)
    if isinstance(value, os.PathLike):
        return os.fspath(value)

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("task result mapping keys must be strings")
            normalized[key] = _json_ready(item)
        return normalized
    if isinstance(value, tuple) and hasattr(value, "_asdict"):
        return _json_ready(value._asdict())
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=repr)]
    raise TypeError(f"task result values must be JSON-compatible, got {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class TaskResult:
    """User-facing envelope returned from workflow and task boundaries."""

    ok: bool
    output: Any = None
    best_output: Any = None
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    attempt_count: int = 0
    events: tuple[TaskEvent, ...] = field(default_factory=tuple)
    artifacts: tuple[ArtifactReference, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.ok, bool):
            raise TypeError("ok must be a bool")
        if isinstance(self.attempt_count, bool) or not isinstance(self.attempt_count, int):
            raise TypeError("attempt_count must be an int")
        if self.attempt_count < 0:
            raise ValueError("attempt_count must be non-negative")

        object.__setattr__(self, "diagnostics", _normalize_diagnostics(self.diagnostics))
        object.__setattr__(self, "events", _normalize_events(self.events))
        object.__setattr__(self, "artifacts", _normalize_artifacts(self.artifacts))
        if self.ok and self.best_output is None and self.output is not None:
            object.__setattr__(self, "best_output", self.output)

    def unwrap(self) -> Any:
        """Return the accepted output or raise an error carrying this result."""

        if self.ok:
            return self.output
        raise TaskResultError(self)

    def output_or(self, default: T) -> Any | T:
        """Return the accepted output on success, otherwise ``default``."""

        if self.ok:
            return self.output
        return default

    def require_ok(self) -> "TaskResult":
        """Return this result when successful, otherwise raise ``TaskResultError``."""

        if self.ok:
            return self
        raise TaskResultError(self)

    def best_available(self) -> Any:
        """Return the accepted output, or the best preserved candidate on failure."""

        if self.ok:
            return self.output
        if self.best_output is not None:
            return self.best_output
        return self.output

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": _json_ready(self.output),
            "best_output": _json_ready(self.best_output),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "attempt_count": self.attempt_count,
            "events": [event.to_dict() for event in self.events],
            "artifacts": [_artifact_to_dict(artifact) for artifact in self.artifacts],
        }

    def to_json(self, *, indent: int | None = 2, sort_keys: bool = True) -> str:
        return json.dumps(self.to_dict(), allow_nan=False, indent=indent, sort_keys=sort_keys)


__all__ = ["ArtifactReference", "TaskResult", "TaskResultError"]
