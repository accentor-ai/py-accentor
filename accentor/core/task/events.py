from __future__ import annotations

"""Canonical task event records consumed by observation modules."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from accentor.core.task.diagnostics import Diagnostic, JsonValue, _normalize_json_value, _plain_json_value


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_metadata(value: Mapping[str, Any] | None, *, field_name: str) -> Mapping[str, JsonValue] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return _normalize_json_value(value)  # type: ignore[return-value]


def _normalize_details(details: Mapping[str, Any] | None) -> Mapping[str, JsonValue]:
    normalized = _normalize_metadata(details, field_name="details")
    return normalized if normalized is not None else MappingProxyType({})


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


def _normalize_artifacts(items: Sequence[Mapping[str, Any]] | None) -> tuple[Mapping[str, JsonValue], ...]:
    if items is None:
        return ()
    normalized: list[Mapping[str, JsonValue]] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise TypeError("artifacts must contain metadata mappings")
        normalized.append(_normalize_json_value(item))  # type: ignore[arg-type]
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class TaskEvent:
    """JSON-stable event record for task, workflow, and observer plumbing."""

    event_type: str
    timestamp: str = field(default_factory=_utc_now_iso)
    workflow: str | None = None
    task: str | None = None
    stage: str | None = None
    attempt: int | None = None
    status: str | None = None
    message: str | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    artifacts: tuple[Mapping[str, JsonValue], ...] = ()
    validation: Mapping[str, JsonValue] | None = None
    routing: Mapping[str, JsonValue] | None = None
    repair: Mapping[str, JsonValue] | None = None
    details: Mapping[str, JsonValue] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not self.event_type:
            raise ValueError("event_type is required")
        if self.attempt is not None and self.attempt < 0:
            raise ValueError("attempt must be non-negative")
        object.__setattr__(self, "diagnostics", _normalize_diagnostics(self.diagnostics))
        object.__setattr__(self, "artifacts", _normalize_artifacts(self.artifacts))
        object.__setattr__(self, "validation", _normalize_metadata(self.validation, field_name="validation"))
        object.__setattr__(self, "routing", _normalize_metadata(self.routing, field_name="routing"))
        object.__setattr__(self, "repair", _normalize_metadata(self.repair, field_name="repair"))
        object.__setattr__(self, "details", _normalize_details(self.details))

    @classmethod
    def workflow_started(
        cls,
        *,
        workflow: str,
        task: str | None = None,
        message: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "TaskEvent":
        return cls(
            event_type="workflow.started",
            workflow=workflow,
            task=task,
            status="started",
            message=message,
            details=details,
        )

    @classmethod
    def workflow_completed(
        cls,
        *,
        workflow: str,
        task: str | None = None,
        status: str = "completed",
        message: str | None = None,
        diagnostics: Sequence[Diagnostic | Mapping[str, Any]] | None = None,
        artifacts: Sequence[Mapping[str, Any]] | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "TaskEvent":
        return cls(
            event_type="workflow.completed",
            workflow=workflow,
            task=task,
            status=status,
            message=message,
            diagnostics=diagnostics,
            artifacts=artifacts,
            details=details,
        )

    @classmethod
    def stage_started(
        cls,
        *,
        stage: str,
        workflow: str | None = None,
        task: str | None = None,
        attempt: int | None = None,
        message: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "TaskEvent":
        return cls(
            event_type="stage.started",
            workflow=workflow,
            task=task,
            stage=stage,
            attempt=attempt,
            status="started",
            message=message,
            details=details,
        )

    @classmethod
    def stage_completed(
        cls,
        *,
        stage: str,
        workflow: str | None = None,
        task: str | None = None,
        attempt: int | None = None,
        status: str = "completed",
        message: str | None = None,
        diagnostics: Sequence[Diagnostic | Mapping[str, Any]] | None = None,
        artifacts: Sequence[Mapping[str, Any]] | None = None,
        validation: Mapping[str, Any] | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "TaskEvent":
        return cls(
            event_type="stage.completed",
            workflow=workflow,
            task=task,
            stage=stage,
            attempt=attempt,
            status=status,
            message=message,
            diagnostics=diagnostics,
            artifacts=artifacts,
            validation=validation,
            details=details,
        )

    @classmethod
    def attempt_started(
        cls,
        *,
        attempt: int,
        stage: str | None = None,
        workflow: str | None = None,
        task: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "TaskEvent":
        return cls(
            event_type="attempt.started",
            workflow=workflow,
            task=task,
            stage=stage,
            attempt=attempt,
            status="started",
            details=details,
        )

    @classmethod
    def attempt_completed(
        cls,
        *,
        attempt: int,
        stage: str | None = None,
        workflow: str | None = None,
        task: str | None = None,
        status: str = "completed",
        diagnostics: Sequence[Diagnostic | Mapping[str, Any]] | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "TaskEvent":
        return cls(
            event_type="attempt.completed",
            workflow=workflow,
            task=task,
            stage=stage,
            attempt=attempt,
            status=status,
            diagnostics=diagnostics,
            details=details,
        )

    @classmethod
    def validation_recorded(
        cls,
        *,
        validation: Mapping[str, Any],
        stage: str | None = None,
        workflow: str | None = None,
        task: str | None = None,
        attempt: int | None = None,
        status: str | None = None,
        diagnostics: Sequence[Diagnostic | Mapping[str, Any]] | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "TaskEvent":
        return cls(
            event_type="validation.recorded",
            workflow=workflow,
            task=task,
            stage=stage,
            attempt=attempt,
            status=status,
            diagnostics=diagnostics,
            validation=validation,
            details=details,
        )

    @classmethod
    def routing_decided(
        cls,
        *,
        routing: Mapping[str, Any],
        workflow: str | None = None,
        task: str | None = None,
        stage: str | None = None,
        message: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "TaskEvent":
        return cls(
            event_type="routing.decided",
            workflow=workflow,
            task=task,
            stage=stage,
            status="selected",
            message=message,
            routing=routing,
            details=details,
        )

    @classmethod
    def repair_recorded(
        cls,
        *,
        repair: Mapping[str, Any],
        workflow: str | None = None,
        task: str | None = None,
        stage: str | None = None,
        attempt: int | None = None,
        status: str | None = None,
        diagnostics: Sequence[Diagnostic | Mapping[str, Any]] | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "TaskEvent":
        return cls(
            event_type="repair.recorded",
            workflow=workflow,
            task=task,
            stage=stage,
            attempt=attempt,
            status=status,
            diagnostics=diagnostics,
            repair=repair,
            details=details,
        )

    @classmethod
    def artifact_recorded(
        cls,
        *,
        artifact: Mapping[str, Any],
        workflow: str | None = None,
        task: str | None = None,
        stage: str | None = None,
        attempt: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "TaskEvent":
        return cls(
            event_type="artifact.recorded",
            workflow=workflow,
            task=task,
            stage=stage,
            attempt=attempt,
            status="recorded",
            artifacts=(artifact,),
            details=details,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "workflow": self.workflow,
            "task": self.task,
            "stage": self.stage,
            "attempt": self.attempt,
            "status": self.status,
            "message": self.message,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "artifacts": [_plain_json_value(artifact) for artifact in self.artifacts],
            "validation": _plain_json_value(self.validation) if self.validation is not None else None,
            "routing": _plain_json_value(self.routing) if self.routing is not None else None,
            "repair": _plain_json_value(self.repair) if self.repair is not None else None,
            "details": _plain_json_value(self.details),
        }


__all__ = ["TaskEvent"]
