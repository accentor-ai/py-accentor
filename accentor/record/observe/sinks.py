from __future__ import annotations

from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence, TypeAlias

try:  # Imported for type compatibility with the canonical WP-01 records.
    from accentor.core.task.diagnostics import Diagnostic
except ImportError:  # pragma: no cover - only used while parallel WP-01 files settle.
    Diagnostic: TypeAlias = Any

try:
    from accentor.core.task.events import TaskEvent
except ImportError:  # pragma: no cover - only used while parallel WP-01 files settle.
    TaskEvent: TypeAlias = Any


JsonValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | list["JsonValue"]
    | dict[str, "JsonValue"]
)

DEFAULT_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "input",
        "inputs",
        "prompt",
        "prompts",
        "raw_input",
        "raw_inputs",
        "raw_note",
        "raw_prompt",
        "customer_note",
        "request",
        "request_body",
        "messages",
        "success_criteria",
    }
)
REDACTED_VALUE = "[REDACTED]"


class ObservationSink(Protocol):
    """Receives already serialized, redaction-safe task events."""

    def emit(self, event: Mapping[str, JsonValue]) -> None:
        """Persist or forward one event."""

    def flush(self) -> None:
        """Flush buffered events."""

    def close(self) -> None:
        """Release sink resources."""


@dataclass(frozen=True)
class ObservationPolicy:
    """Policy for serializing task events into ordinary observation logs."""

    redact_sensitive_fields: bool = True
    sensitive_field_names: frozenset[str] = DEFAULT_SENSITIVE_FIELD_NAMES
    replacement: str = REDACTED_VALUE

    def redact(self, value: JsonValue) -> JsonValue:
        if not self.redact_sensitive_fields:
            return value
        return _redact_sensitive_fields(value, self)


class TaskObserver:
    """Captures canonical task events in memory and forwards them to sinks."""

    def __init__(
        self,
        sinks: Iterable[ObservationSink] | None = None,
        *,
        policy: ObservationPolicy | None = None,
    ) -> None:
        self.sinks = list(sinks or ())
        self.policy = policy or ObservationPolicy()
        self.events: list[dict[str, JsonValue]] = []
        self._closed = False

    def emit(self, event: TaskEvent) -> dict[str, JsonValue]:
        if self._closed:
            raise ValueError("cannot emit to a closed TaskObserver")

        serialized = serialize_task_event(event, policy=self.policy)
        self.events.append(serialized)
        for sink in self.sinks:
            sink.emit(serialized)
        return serialized

    record = emit

    def add_sink(self, sink: ObservationSink) -> None:
        if self._closed:
            raise ValueError("cannot add a sink to a closed TaskObserver")
        self.sinks.append(sink)

    def flush(self) -> None:
        for sink in self.sinks:
            sink.flush()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.flush()
        finally:
            for sink in self.sinks:
                sink.close()
            self._closed = True

    def __enter__(self) -> "TaskObserver":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def serialize_task_event(
    event: TaskEvent,
    *,
    policy: ObservationPolicy | None = None,
) -> dict[str, JsonValue]:
    """Return a JSON-stable, redaction-safe dictionary for a task event."""

    raw_event = _record_to_mapping(event)
    json_event = json_safe(raw_event)
    if not isinstance(json_event, dict):
        raise TypeError("task events must serialize to a JSON object")
    redacted_event = (policy or ObservationPolicy()).redact(json_event)
    if not isinstance(redacted_event, dict):
        raise TypeError("task events must serialize to a JSON object")
    return redacted_event


def json_safe(value: Any) -> JsonValue:
    """Convert stdlib record-shaped values into deterministic JSON values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, Path):
        return str(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return json_safe(to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple) and hasattr(value, "_asdict"):
        return json_safe(value._asdict())
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [json_safe(item) for item in sorted(value, key=repr)]
    if hasattr(value, "__dict__"):
        return json_safe(vars(value))
    return repr(value)


def _record_to_mapping(record: Any) -> Mapping[str, Any]:
    to_dict = getattr(record, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        if not isinstance(data, Mapping):
            raise TypeError("TaskEvent.to_dict() must return a mapping")
        return data
    if is_dataclass(record) and not isinstance(record, type):
        return {field.name: getattr(record, field.name) for field in fields(record)}
    if isinstance(record, Mapping):
        return record
    if hasattr(record, "__dict__"):
        return vars(record)
    raise TypeError("task events must be mappings, dataclasses, or expose to_dict()")


def _redact_sensitive_fields(value: JsonValue, policy: ObservationPolicy) -> JsonValue:
    if isinstance(value, dict):
        redacted: dict[str, JsonValue] = {}
        for key, item in value.items():
            if _is_sensitive_key(key, policy.sensitive_field_names):
                redacted[key] = policy.replacement
            else:
                redacted[key] = _redact_sensitive_fields(item, policy)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_fields(item, policy) for item in value]
    return value


def _is_sensitive_key(key: str, sensitive_field_names: Sequence[str]) -> bool:
    normalized = key.lower().strip()
    return normalized in sensitive_field_names


__all__ = [
    "DEFAULT_SENSITIVE_FIELD_NAMES",
    "JsonValue",
    "ObservationPolicy",
    "ObservationSink",
    "REDACTED_VALUE",
    "TaskObserver",
    "json_safe",
    "serialize_task_event",
]
