from __future__ import annotations

"""Declarative phase records for multi-phase tasks."""

import json
import math
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import Enum
from types import MappingProxyType
from typing import Any

from accentor.evaluate.validation.base import ValidatorLike


PathInput = str | os.PathLike[str]
PathInputs = PathInput | Iterable[PathInput] | None


def _path_text(path: PathInput) -> str:
    raw = os.fspath(path)
    if isinstance(raw, bytes):
        raise TypeError("phase paths must be text, not bytes")
    if not raw:
        raise ValueError("phase paths must not be empty")
    return raw


def _as_path_tuple(value: PathInputs) -> tuple[PathInput, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, os.PathLike)):
        items = (value,)
    else:
        items = tuple(value)

    seen: set[str] = set()
    normalized: list[PathInput] = []
    for item in items:
        key = _path_text(item)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    return tuple(normalized)


def _as_validators(value: Sequence[ValidatorLike] | None) -> tuple[ValidatorLike, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        raise TypeError("validators must be a sequence of validator objects, not a string")
    return tuple(value)


def _validator_name(validator: Any) -> str:
    if isinstance(validator, str):
        return validator
    if isinstance(validator, type):
        return validator.__name__
    name = getattr(validator, "__name__", None)
    if name:
        return str(name)
    return validator.__class__.__name__


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("phase values must not contain non-finite floats")
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
                raise TypeError("phase metadata keys must be strings")
            normalized[key] = _json_ready(item)
        return normalized
    if isinstance(value, tuple) and hasattr(value, "_asdict"):
        return _json_ready(value._asdict())
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=repr)]
    raise TypeError(f"phase values must be JSON-compatible, got {type(value).__name__}")


def _metadata_proxy(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    ready = _json_ready(dict(value or {}))
    if not isinstance(ready, dict):
        raise TypeError("phase metadata must serialize to a mapping")
    return MappingProxyType(ready)


def _path_list(paths: Sequence[PathInput]) -> list[str]:
    return [_path_text(path) for path in paths]


@dataclass(frozen=True, slots=True, init=False)
class Phase:
    """One ordered phase in a task that shares a persistent agent session."""

    name: str
    prompt: str
    workspace_files: tuple[PathInput, ...] = field(default_factory=tuple)
    revoke_files: tuple[PathInput, ...] = field(default_factory=tuple)
    validators: tuple[ValidatorLike, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        name: str,
        prompt: str,
        *,
        workspace_files: PathInputs = None,
        revoke_files: PathInputs = None,
        validators: Sequence[ValidatorLike] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("phase name is required")
        if not isinstance(prompt, str):
            raise TypeError("phase prompt must be a string")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(
            self,
            "workspace_files",
            _as_path_tuple(workspace_files),
        )
        object.__setattr__(
            self,
            "revoke_files",
            _as_path_tuple(revoke_files),
        )
        object.__setattr__(self, "validators", _as_validators(validators))
        object.__setattr__(self, "metadata", _metadata_proxy(metadata))

    @property
    def readable_files(self) -> tuple[PathInput, ...]:
        """Alias used by workspace and permission compilers."""

        return self.workspace_files

    @property
    def revoked_files(self) -> tuple[PathInput, ...]:
        """Alias used by revocation-aware runners."""

        return self.revoke_files

    @property
    def editable_files(self) -> tuple[PathInput, ...]:
        """Phase v1 does not grant write access."""

        return ()

    @property
    def network(self) -> bool:
        """Phase v1 does not grant additional network access."""

        return False

    @property
    def validator_names(self) -> tuple[str, ...]:
        """Stable validator identifiers safe for public phase records."""

        return tuple(_validator_name(validator) for validator in self.validators)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "prompt": self.prompt,
            "workspace_files": _path_list(self.workspace_files),
            "revoke_files": _path_list(self.revoke_files),
            "editable_files": [],
            "network": False,
            "validators": list(self.validator_names),
            "metadata": _json_ready(self.metadata),
        }

    def to_json(self, *, indent: int | None = 2, sort_keys: bool = True) -> str:
        return json.dumps(self.to_dict(), allow_nan=False, indent=indent, sort_keys=sort_keys)


__all__ = ["PathInput", "PathInputs", "Phase"]
