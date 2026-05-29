from __future__ import annotations

from accentor.record.observe import events
from accentor.record.observe.jsonl import JsonlSink
from accentor.record.observe.sinks import (
    DEFAULT_SENSITIVE_FIELD_NAMES,
    REDACTED_VALUE,
    ObservationPolicy,
    ObservationSink,
    TaskObserver,
    json_safe,
    serialize_task_event,
)


def __getattr__(name: str) -> object:
    if name == "TaskEvent":
        from accentor.core.task.events import TaskEvent

        return TaskEvent
    raise AttributeError(name)


__all__ = [
    "DEFAULT_SENSITIVE_FIELD_NAMES",
    "JsonlSink",
    "ObservationPolicy",
    "ObservationSink",
    "REDACTED_VALUE",
    "TaskEvent",
    "TaskObserver",
    "events",
    "json_safe",
    "serialize_task_event",
]
