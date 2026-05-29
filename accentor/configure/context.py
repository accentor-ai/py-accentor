from __future__ import annotations

"""Configuration-time context selection records."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any


FRAMEWORK_INJECTED_NAMES = frozenset({"ctx", "routed_context", "success_criteria"})


def _plain_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (Path,)):
        return str(value)
    if isinstance(value, Enum):
        return _plain_value(value.value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _plain_value(to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return _plain_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_plain_value(item) for item in sorted(value, key=repr)]
    return repr(value)


def user_call_args(call_args: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return user-supplied call arguments without framework-injected values."""

    return {
        str(key): _plain_value(value)
        for key, value in (call_args or {}).items()
        if str(key) not in FRAMEWORK_INJECTED_NAMES
    }


def _copy_metadata(metadata: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType({str(key): _plain_value(value) for key, value in (metadata or {}).items()})


@dataclass(frozen=True, slots=True)
class ConfigureContext:
    """Serializable context selected during configuration."""

    value: Any
    name: str | None = None
    source: str = "static"
    selected_index: int | None = None
    user_input: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if self.name is not None and not isinstance(self.name, str):
            raise TypeError("name must be a string or None")
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("source must be a non-empty string")
        if self.selected_index is not None:
            if isinstance(self.selected_index, bool) or not isinstance(self.selected_index, int):
                raise TypeError("selected_index must be an int or None")
            if self.selected_index < 0:
                raise ValueError("selected_index must be non-negative")

        object.__setattr__(self, "value", _plain_value(self.value))
        object.__setattr__(self, "user_input", MappingProxyType(user_call_args(self.user_input)))
        object.__setattr__(self, "metadata", _copy_metadata(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "selected_index": self.selected_index,
            "value": _plain_value(self.value),
            "user_input": dict(self.user_input),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ContextSelector:
    """Deterministic static/list/call-argument context selector."""

    kind: str
    values: tuple[Any, ...] = ()
    name: str | None = None
    key: str | None = None
    default: Any = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if self.kind not in {"static", "list", "call_arg"}:
            raise ValueError("kind must be one of: static, list, call_arg")
        if self.name is not None and not isinstance(self.name, str):
            raise TypeError("name must be a string or None")
        if self.kind == "call_arg" and not self.key:
            raise ValueError("call_arg selectors require a key")
        object.__setattr__(self, "values", tuple(_plain_value(value) for value in self.values))
        object.__setattr__(self, "metadata", _copy_metadata(self.metadata))

    @classmethod
    def static(
        cls,
        value: Any,
        *,
        name: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ContextSelector":
        return cls(kind="static", values=(value,), name=name, metadata=metadata or {})

    @classmethod
    def from_list(
        cls,
        values: Sequence[Any],
        *,
        name: str | None = None,
        selection_key: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ContextSelector":
        return cls(
            kind="list",
            values=tuple(values),
            name=name,
            key=selection_key,
            metadata=metadata or {},
        )

    @classmethod
    def from_call_arg(
        cls,
        key: str,
        *,
        name: str | None = None,
        default: Any = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ContextSelector":
        return cls(kind="call_arg", name=name, key=key, default=default, metadata=metadata or {})

    def select(self, call_args: Mapping[str, Any] | None = None) -> ConfigureContext:
        args = dict(call_args or {})
        user_input = user_call_args(args)

        if self.kind == "static":
            return ConfigureContext(
                value=self.values[0],
                name=self.name,
                source="static",
                user_input=user_input,
                metadata=self.metadata,
            )

        if self.kind == "list":
            if not self.values:
                raise ValueError("list context selector requires at least one value")
            selected_index: int | None = None
            value: Any = list(self.values)
            if self.key and self.key in args:
                requested = args[self.key]
                if isinstance(requested, bool):
                    raise TypeError("list context selection index must be an int, not bool")
                if isinstance(requested, int):
                    if requested < 0 or requested >= len(self.values):
                        raise IndexError("list context selection index is out of range")
                    selected_index = requested
                    value = self.values[requested]
                elif requested in self.values:
                    selected_index = self.values.index(requested)
                    value = requested
                else:
                    raise ValueError("list context selection value is not present")
            return ConfigureContext(
                value=value,
                name=self.name,
                source="list",
                selected_index=selected_index,
                user_input=user_input,
                metadata=self.metadata,
            )

        value = args.get(self.key, self.default)
        return ConfigureContext(
            value=value,
            name=self.name,
            source=f"call_arg:{self.key}",
            user_input=user_input,
            metadata=self.metadata,
        )

    def __call__(self, call_args: Mapping[str, Any] | None = None) -> ConfigureContext:
        return self.select(call_args)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "key": self.key,
            "values": [_plain_value(value) for value in self.values],
            "default": _plain_value(self.default),
            "metadata": dict(self.metadata),
        }


__all__ = [
    "ConfigureContext",
    "ContextSelector",
    "FRAMEWORK_INJECTED_NAMES",
    "user_call_args",
]
