from __future__ import annotations

"""Core step records and execution context plumbing."""

import inspect
from dataclasses import dataclass, field, fields, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence

from accentor.core.task.diagnostics import Diagnostic, JsonValue, _normalize_json_value, _plain_json_value
from accentor.core.task.events import TaskEvent
from accentor.core.task.results import (
    ArtifactReference,
    TaskResult,
    _artifact_to_dict,
    _json_ready,
    _normalize_artifacts,
    _normalize_diagnostics,
    _normalize_events,
)
from accentor.record.artifacts import ArtifactStore
from accentor.record.observe import TaskObserver


class StepKind(str, Enum):
    """Stable step kind strings used in execution records and event logs."""

    EXECUTE = "execute"
    DISPATCH = "dispatch"
    EXTRACT = "extract"
    VALIDATE = "validate"
    ROUTE = "route"
    RECOVER = "recover"
    COMMIT = "commit"

    def __str__(self) -> str:
        return self.value


class StepHandler(Protocol):
    """Callable shape accepted by ``Step``.

    User callables are not required to accept context. If they declare a
    parameter named ``ctx``, ``Step`` injects the current ``StepContext``.
    """

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        ...


_UNSET = object()


def _normalize_kind(kind: StepKind | str) -> StepKind:
    if isinstance(kind, StepKind):
        return kind
    return StepKind(str(kind))


def _normalize_nonempty_text(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    return value


def _normalize_json_mapping(value: Mapping[str, Any] | None, *, field_name: str) -> Mapping[str, JsonValue]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    normalized = _normalize_json_value(value)
    if not isinstance(normalized, Mapping):
        raise TypeError(f"{field_name} must normalize to a mapping")
    return normalized


def _merge_json_mapping(
    base: Mapping[str, JsonValue],
    updates: Mapping[str, Any] | None,
    *,
    field_name: str,
) -> Mapping[str, JsonValue]:
    if updates is None:
        return base
    merged = dict(_plain_json_value(base))
    merged.update(updates)
    return _normalize_json_mapping(merged, field_name=field_name)


def _record_snapshot(value: Any) -> Any:
    if value is None:
        return None
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    root = getattr(value, "root", None)
    if root is None:
        root = getattr(value, "workspace_root", None)
    snapshot: dict[str, Any] = {"type": type(value).__name__}
    if root is not None:
        snapshot["root"] = str(root)
    return snapshot


def _normalise_artifact_root(
    artifact_root: str | Path | None,
    artifact_store: ArtifactStore | None,
) -> tuple[Path | None, ArtifactStore | None]:
    if artifact_store is not None and not isinstance(artifact_store, ArtifactStore):
        raise TypeError("artifact_store must be an ArtifactStore")

    if artifact_store is None and artifact_root is not None:
        artifact_store = ArtifactStore(artifact_root)

    if artifact_store is not None:
        store_root = artifact_store.root
        if artifact_root is not None and Path(artifact_root).resolve(strict=False) != store_root:
            raise ValueError("artifact_root must match artifact_store.root")
        return store_root, artifact_store

    return (Path(artifact_root) if artifact_root is not None else None), None


@dataclass(frozen=True, slots=True)
class StepContext:
    """Runtime context threaded through Accentor's internal step pipeline."""

    run_id: str
    task_id: str
    stage: str | None = None
    attempt: int = 0
    artifact_root: Path | None = None
    artifact_store: ArtifactStore | None = None
    observer: TaskObserver | None = None
    workspace: Any = None
    permissions: Any = None
    routing: Mapping[str, JsonValue] = field(default_factory=lambda: MappingProxyType({}))
    validation: Mapping[str, JsonValue] = field(default_factory=lambda: MappingProxyType({}))
    metadata: Mapping[str, JsonValue] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        run_id = _normalize_nonempty_text(self.run_id, field_name="run_id")
        task_id = _normalize_nonempty_text(self.task_id, field_name="task_id")
        stage = _normalize_nonempty_text(self.stage, field_name="stage")

        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int):
            raise TypeError("attempt must be an int")
        if self.attempt < 0:
            raise ValueError("attempt must be non-negative")

        artifact_root, artifact_store = _normalise_artifact_root(self.artifact_root, self.artifact_store)

        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "artifact_root", artifact_root)
        object.__setattr__(self, "artifact_store", artifact_store)
        object.__setattr__(self, "routing", _normalize_json_mapping(self.routing, field_name="routing"))
        object.__setattr__(self, "validation", _normalize_json_mapping(self.validation, field_name="validation"))
        object.__setattr__(self, "metadata", _normalize_json_mapping(self.metadata, field_name="metadata"))

    @property
    def routing_decisions(self) -> Mapping[str, JsonValue]:
        return self.routing

    @property
    def validation_state(self) -> Mapping[str, JsonValue]:
        return self.validation

    @classmethod
    def root(
        cls,
        *,
        run_id: str,
        task_id: str,
        artifact_root: str | Path | None = None,
        artifact_store: ArtifactStore | None = None,
        observer: TaskObserver | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "StepContext":
        """Build the root context a workflow wrapper would thread internally."""

        return cls(
            run_id=run_id,
            task_id=task_id,
            artifact_root=artifact_root,
            artifact_store=artifact_store,
            observer=observer,
            metadata=metadata,
        )

    def derive(
        self,
        *,
        run_id: str | object = _UNSET,
        task_id: str | object = _UNSET,
        stage: str | None | object = _UNSET,
        attempt: int | object = _UNSET,
        artifact_root: str | Path | None | object = _UNSET,
        artifact_store: ArtifactStore | None | object = _UNSET,
        observer: TaskObserver | None | object = _UNSET,
        workspace: Any = _UNSET,
        permissions: Any = _UNSET,
        routing: Mapping[str, Any] | None = None,
        validation: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "StepContext":
        """Return a child context with selected fields changed.

        ``routing``, ``validation``, and ``metadata`` are merged onto the
        current context. Use ``with_updates`` when exact replacement is needed.
        """

        updates: dict[str, Any] = {}
        for key, value in {
            "run_id": run_id,
            "task_id": task_id,
            "stage": stage,
            "attempt": attempt,
            "artifact_root": artifact_root,
            "artifact_store": artifact_store,
            "observer": observer,
            "workspace": workspace,
            "permissions": permissions,
        }.items():
            if value is not _UNSET:
                updates[key] = value

        if routing is not None:
            updates["routing"] = _merge_json_mapping(self.routing, routing, field_name="routing")
        if validation is not None:
            updates["validation"] = _merge_json_mapping(self.validation, validation, field_name="validation")
        if metadata is not None:
            updates["metadata"] = _merge_json_mapping(self.metadata, metadata, field_name="metadata")
        return replace(self, **updates)

    def with_updates(self, **updates: Any) -> "StepContext":
        """Return a context with exact field replacements."""

        aliases = {
            "routing_decisions": "routing",
            "validation_state": "validation",
        }
        normalized: dict[str, Any] = {}
        field_names = {item.name for item in fields(self)}
        for key, value in updates.items():
            normalized_key = aliases.get(key, key)
            if normalized_key not in field_names:
                raise TypeError(f"unknown StepContext field: {key}")
            normalized[normalized_key] = value
        return replace(self, **normalized)

    def to_dict(self) -> dict[str, Any]:
        observer_snapshot = None
        if self.observer is not None:
            observer_snapshot = {"type": type(self.observer).__name__, "event_count": len(self.observer.events)}

        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "stage": self.stage,
            "attempt": self.attempt,
            "artifact_root": str(self.artifact_root) if self.artifact_root is not None else None,
            "artifact_store": _record_snapshot(self.artifact_store),
            "observer": observer_snapshot,
            "workspace": _record_snapshot(self.workspace),
            "permissions": _record_snapshot(self.permissions),
            "routing": _plain_json_value(self.routing),
            "validation": _plain_json_value(self.validation),
            "metadata": _plain_json_value(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class StepResult:
    """Structured result for one internal step execution."""

    ok: bool
    output: Any = None
    best_output: Any = None
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    events: tuple[TaskEvent, ...] = field(default_factory=tuple)
    artifacts: tuple[ArtifactReference, ...] = field(default_factory=tuple)
    step: str | None = None
    kind: StepKind | None = None
    attempt: int | None = None
    context: StepContext | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not isinstance(self.ok, bool):
            raise TypeError("ok must be a bool")
        if self.step is not None:
            object.__setattr__(self, "step", _normalize_nonempty_text(self.step, field_name="step"))
        if self.kind is not None:
            object.__setattr__(self, "kind", _normalize_kind(self.kind))

        attempt = self.attempt
        if attempt is None and self.context is not None:
            attempt = self.context.attempt
        if attempt is not None:
            if isinstance(attempt, bool) or not isinstance(attempt, int):
                raise TypeError("attempt must be an int")
            if attempt < 0:
                raise ValueError("attempt must be non-negative")
            object.__setattr__(self, "attempt", attempt)

        object.__setattr__(self, "diagnostics", _normalize_diagnostics(self.diagnostics))
        object.__setattr__(self, "events", _normalize_events(self.events))
        object.__setattr__(self, "artifacts", _normalize_artifacts(self.artifacts))
        object.__setattr__(self, "metadata", _normalize_json_mapping(self.metadata, field_name="metadata"))
        if self.ok and self.best_output is None and self.output is not None:
            object.__setattr__(self, "best_output", self.output)

    @classmethod
    def success(
        cls,
        output: Any = None,
        *,
        step: str | None = None,
        kind: StepKind | str | None = None,
        attempt: int | None = None,
        context: StepContext | None = None,
        events: Sequence[TaskEvent | Mapping[str, Any]] | None = None,
        artifacts: Sequence[ArtifactReference] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "StepResult":
        return cls(
            ok=True,
            output=output,
            step=step,
            kind=_normalize_kind(kind) if kind is not None else None,
            attempt=attempt,
            context=context,
            events=tuple(events or ()),
            artifacts=tuple(artifacts or ()),
            metadata=metadata or {},
        )

    @classmethod
    def failure(
        cls,
        *,
        diagnostics: Sequence[Diagnostic | Mapping[str, Any]] | None = None,
        diagnostic: Diagnostic | Mapping[str, Any] | None = None,
        best_output: Any = None,
        step: str | None = None,
        kind: StepKind | str | None = None,
        attempt: int | None = None,
        context: StepContext | None = None,
        events: Sequence[TaskEvent | Mapping[str, Any]] | None = None,
        artifacts: Sequence[ArtifactReference] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "StepResult":
        all_diagnostics = [*(diagnostics or ())]
        if diagnostic is not None:
            all_diagnostics.append(diagnostic)
        return cls(
            ok=False,
            best_output=best_output,
            diagnostics=tuple(all_diagnostics),
            step=step,
            kind=_normalize_kind(kind) if kind is not None else None,
            attempt=attempt,
            context=context,
            events=tuple(events or ()),
            artifacts=tuple(artifacts or ()),
            metadata=metadata or {},
        )

    def with_updates(self, **updates: Any) -> "StepResult":
        return replace(self, **updates)

    def unwrap(self) -> Any:
        if self.ok:
            return self.output
        if self.diagnostics:
            diagnostic = self.diagnostics[0]
            raise RuntimeError(f"StepResult is not ok: [{diagnostic.code}] {diagnostic.message}")
        raise RuntimeError("StepResult is not ok")

    def to_task_result(self) -> TaskResult:
        attempt_count = self.attempt + 1 if self.attempt is not None else 0
        return TaskResult(
            ok=self.ok,
            output=self.output,
            best_output=self.best_output,
            diagnostics=self.diagnostics,
            attempt_count=attempt_count,
            events=self.events,
            artifacts=self.artifacts,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "step": self.step,
            "kind": self.kind.value if self.kind is not None else None,
            "attempt": self.attempt,
            "output": _json_ready(self.output),
            "best_output": _json_ready(self.best_output),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "events": [event.to_dict() for event in self.events],
            "artifacts": [_artifact_to_dict(artifact) for artifact in self.artifacts],
            "context": self.context.to_dict() if self.context is not None else None,
            "metadata": _plain_json_value(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class Step:
    """Executable unit used by composition helpers and decorators."""

    name: str
    handler: Callable[..., Any] | None = None
    kind: StepKind | str = StepKind.EXECUTE
    metadata: Mapping[str, JsonValue] = field(default_factory=lambda: MappingProxyType({}))
    catch_exceptions: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _normalize_nonempty_text(self.name, field_name="name"))
        object.__setattr__(self, "kind", _normalize_kind(self.kind))
        object.__setattr__(self, "metadata", _normalize_json_mapping(self.metadata, field_name="metadata"))
        if self.handler is not None and not callable(self.handler):
            raise TypeError("handler must be callable")

    def __call__(self, ctx: StepContext, *args: Any, **kwargs: Any) -> StepResult:
        return self.run(ctx, *args, **kwargs)

    def run(self, ctx: StepContext, *args: Any, **kwargs: Any) -> StepResult:
        if not isinstance(ctx, StepContext):
            raise TypeError("ctx must be a StepContext")
        if self.handler is None:
            return StepResult.failure(
                diagnostic=Diagnostic.error(
                    "step.handler_missing",
                    f"Step {self.name!r} does not have a handler.",
                    source="core.steps",
                ),
                step=self.name,
                kind=self.kind,
                context=ctx,
                metadata=self.metadata,
            )

        try:
            output = _call_handler(self.handler, ctx, *args, **kwargs)
        except Exception as exc:
            if not self.catch_exceptions:
                raise
            return StepResult.failure(
                diagnostic=Diagnostic.error(
                    "step.exception",
                    f"Step {self.name!r} raised {type(exc).__name__}: {exc}",
                    source="core.steps",
                    details={"exception_type": type(exc).__name__},
                ),
                step=self.name,
                kind=self.kind,
                context=ctx,
                metadata=self.metadata,
            )

        return _coerce_step_result(output, step=self, context=ctx)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "has_handler": self.handler is not None,
            "catch_exceptions": self.catch_exceptions,
            "metadata": _plain_json_value(self.metadata),
        }


def _call_handler(handler: Callable[..., Any], ctx: StepContext, *args: Any, **kwargs: Any) -> Any:
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        return handler(*args, **kwargs)

    parameter = signature.parameters.get("ctx")
    if parameter is None or "ctx" in kwargs:
        return handler(*args, **kwargs)
    if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
        return handler(ctx, *args, **kwargs)
    return handler(*args, ctx=ctx, **kwargs)


def _coerce_step_result(output: Any, *, step: Step, context: StepContext) -> StepResult:
    if isinstance(output, StepResult):
        updates: dict[str, Any] = {}
        if output.step is None:
            updates["step"] = step.name
        if output.kind is None:
            updates["kind"] = step.kind
        if output.context is None:
            updates["context"] = context
        if output.attempt is None:
            updates["attempt"] = context.attempt
        if not output.metadata and step.metadata:
            updates["metadata"] = step.metadata
        return output.with_updates(**updates) if updates else output

    if isinstance(output, TaskResult):
        return StepResult(
            ok=output.ok,
            output=output.output,
            best_output=output.best_output,
            diagnostics=output.diagnostics,
            events=output.events,
            artifacts=output.artifacts,
            step=step.name,
            kind=step.kind,
            attempt=context.attempt,
            context=context,
            metadata=step.metadata,
        )

    return StepResult.success(
        output,
        step=step.name,
        kind=step.kind,
        context=context,
        metadata=step.metadata,
    )


__all__ = [
    "Step",
    "StepContext",
    "StepHandler",
    "StepKind",
    "StepResult",
]
