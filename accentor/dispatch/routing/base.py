from __future__ import annotations

"""Deterministic intra-task routing records."""

import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("routing records must not contain non-finite floats")
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (Path, os.PathLike)):
        return os.fspath(value)
    if isinstance(value, Enum):
        return _json_ready(value.value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=repr)]
    return repr(value)


def _mapping_proxy(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError("metadata/details must be a mapping")
    return MappingProxyType({str(key): item for key, item in value.items()})


def _normalize_diagnostics(
    diagnostics: Sequence["RoutingDiagnostic" | Mapping[str, Any]] | None,
) -> tuple["RoutingDiagnostic", ...]:
    if diagnostics is None:
        return ()
    normalized: list[RoutingDiagnostic] = []
    for diagnostic in diagnostics:
        if isinstance(diagnostic, RoutingDiagnostic):
            normalized.append(diagnostic)
        elif isinstance(diagnostic, Mapping):
            normalized.append(RoutingDiagnostic(**diagnostic))
        else:
            to_dict = getattr(diagnostic, "to_dict", None)
            if callable(to_dict):
                payload = to_dict()
                if isinstance(payload, Mapping):
                    normalized.append(RoutingDiagnostic(**payload))
                    continue
            raise TypeError("diagnostics must contain routing diagnostics or mappings")
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class RoutingDiagnostic:
    """Diagnostic emitted while selecting a route."""

    code: str
    message: str
    severity: str = "error"
    source: str = "routing"
    hint: str | None = None
    details: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("routing diagnostic code is required")
        if not self.message:
            raise ValueError("routing diagnostic message is required")
        if self.severity not in {"debug", "info", "warning", "error", "critical"}:
            raise ValueError("routing diagnostic severity is invalid")
        object.__setattr__(self, "details", _mapping_proxy(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "source": self.source,
            "hint": self.hint,
            "details": _json_ready(self.details),
        }


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    """Named candidate context that may be selected by a router."""

    name: str
    context: Any
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("route candidate name is required")
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    def to_dict(self, *, include_context: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "metadata": _json_ready(self.metadata),
        }
        if include_context:
            payload["context"] = _json_ready(self.context)
        return payload


@dataclass(frozen=True, slots=True)
class RoutingContext:
    """Input envelope passed to deterministic intra-task routers."""

    stage: str
    input: Mapping[str, Any]
    candidate_names: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not isinstance(self.stage, str) or not self.stage:
            raise ValueError("routing context stage is required")
        if not isinstance(self.input, Mapping):
            raise TypeError("routing context input must be a mapping")
        object.__setattr__(self, "input", MappingProxyType({str(key): item for key, item in self.input.items()}))
        object.__setattr__(self, "candidate_names", tuple(str(name) for name in self.candidate_names))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "input": _json_ready(self.input),
            "candidate_names": list(self.candidate_names),
            "metadata": _json_ready(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Router output naming the selected candidate and why."""

    selected: str | None
    rationale: str = ""
    confidence: float | None = None
    diagnostics: tuple[RoutingDiagnostic, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    candidates: tuple[str, ...] = ()
    omitted: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.selected is not None and (not isinstance(self.selected, str) or not self.selected):
            raise ValueError("selected route must be a non-empty string or None")
        if self.confidence is not None:
            if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
                raise TypeError("routing confidence must be a number")
            if not math.isfinite(float(self.confidence)) or not 0.0 <= float(self.confidence) <= 1.0:
                raise ValueError("routing confidence must be between 0 and 1")
            object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "rationale", str(self.rationale or ""))
        object.__setattr__(self, "diagnostics", _normalize_diagnostics(self.diagnostics))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))
        object.__setattr__(self, "candidates", tuple(str(name) for name in self.candidates))
        object.__setattr__(self, "omitted", tuple(str(name) for name in self.omitted))

    @classmethod
    def from_any(cls, value: Any) -> "RoutingDecision":
        if isinstance(value, RoutingDecision):
            return value
        if isinstance(value, str):
            return cls(selected=value)
        if isinstance(value, Mapping):
            payload = dict(value)
            selected = payload.pop("selected", payload.pop("name", None))
            return cls(selected=selected, **payload)
        raise TypeError("router must return RoutingDecision, route name, or mapping")

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": self.selected,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "candidates": list(self.candidates),
            "omitted": list(self.omitted),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "metadata": _json_ready(self.metadata),
        }


@runtime_checkable
class Router(Protocol):
    """Callable deterministic router protocol."""

    def __call__(self, context: RoutingContext) -> RoutingDecision | str | Mapping[str, Any]:
        ...


__all__ = [
    "RouteCandidate",
    "Router",
    "RoutingContext",
    "RoutingDecision",
    "RoutingDiagnostic",
]
