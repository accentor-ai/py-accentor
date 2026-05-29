from __future__ import annotations

"""Immutable-ish task run and attempt records."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence

from accentor.core.task.diagnostics import Diagnostic
from accentor.core.task.events import TaskEvent
from accentor.core.task.results import (
    ArtifactReference,
    _artifact_to_dict,
    _json_ready,
    _normalize_artifacts,
    _normalize_diagnostics,
    _normalize_events,
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_timestamp(value: str | datetime | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        if not value:
            raise ValueError(f"{field_name} must not be empty")
        return value
    raise TypeError(f"{field_name} must be an ISO timestamp string or datetime")


def _normalize_attempts(items: Sequence["TaskAttempt" | Mapping[str, Any]] | None) -> tuple["TaskAttempt", ...]:
    if items is None:
        return ()
    normalized: list[TaskAttempt] = []
    for item in items:
        if isinstance(item, TaskAttempt):
            normalized.append(item)
        elif isinstance(item, Mapping):
            normalized.append(TaskAttempt(**item))
        else:
            raise TypeError("attempts must contain TaskAttempt objects or attempt mappings")
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class TaskAttempt:
    """JSON-stable record for one attempt within a task run."""

    run_id: str
    task_id: str
    attempt_index: int
    status: str
    started_at: str | datetime = field(default_factory=_utc_now_iso)
    completed_at: str | datetime | None = None
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    events: tuple[TaskEvent, ...] = field(default_factory=tuple)
    artifacts: tuple[ArtifactReference, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.task_id:
            raise ValueError("task_id is required")
        if isinstance(self.attempt_index, bool) or not isinstance(self.attempt_index, int):
            raise TypeError("attempt_index must be an int")
        if self.attempt_index < 0:
            raise ValueError("attempt_index must be non-negative")
        if not self.status:
            raise ValueError("status is required")

        object.__setattr__(self, "started_at", _normalize_timestamp(self.started_at, field_name="started_at"))
        object.__setattr__(
            self,
            "completed_at",
            _normalize_timestamp(self.completed_at, field_name="completed_at"),
        )
        object.__setattr__(self, "diagnostics", _normalize_diagnostics(self.diagnostics))
        object.__setattr__(self, "events", _normalize_events(self.events))
        object.__setattr__(self, "artifacts", _normalize_artifacts(self.artifacts))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "attempt_index": self.attempt_index,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "events": [event.to_dict() for event in self.events],
            "artifacts": [_artifact_to_dict(artifact) for artifact in self.artifacts],
        }


@dataclass(frozen=True, slots=True)
class TaskRun:
    """JSON-stable record for a workflow or task invocation."""

    run_id: str
    task_id: str
    status: str
    started_at: str | datetime = field(default_factory=_utc_now_iso)
    completed_at: str | datetime | None = None
    attempts: tuple[TaskAttempt, ...] = field(default_factory=tuple)
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    events: tuple[TaskEvent, ...] = field(default_factory=tuple)
    artifacts: tuple[ArtifactReference, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.task_id:
            raise ValueError("task_id is required")
        if not self.status:
            raise ValueError("status is required")

        object.__setattr__(self, "started_at", _normalize_timestamp(self.started_at, field_name="started_at"))
        object.__setattr__(
            self,
            "completed_at",
            _normalize_timestamp(self.completed_at, field_name="completed_at"),
        )
        object.__setattr__(self, "attempts", _normalize_attempts(self.attempts))
        object.__setattr__(self, "diagnostics", _normalize_diagnostics(self.diagnostics))
        object.__setattr__(self, "events", _normalize_events(self.events))
        object.__setattr__(self, "artifacts", _normalize_artifacts(self.artifacts))

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "events": [event.to_dict() for event in self.events],
            "artifacts": [_artifact_to_dict(artifact) for artifact in self.artifacts],
        }

    def to_json(self, *, indent: int | None = 2, sort_keys: bool = True) -> str:
        import json

        return json.dumps(_json_ready(self.to_dict()), allow_nan=False, indent=indent, sort_keys=sort_keys)


__all__ = ["TaskAttempt", "TaskRun"]
