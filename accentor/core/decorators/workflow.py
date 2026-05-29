from __future__ import annotations

"""Workflow decorator and shared decorator runtime state."""

import inspect
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from accentor.core.composition.gates import build_validation_report
from accentor.core.steps.base import StepContext
from accentor.core.task.diagnostics import Diagnostic
from accentor.core.task.events import TaskEvent
from accentor.core.task.results import ArtifactReference, TaskResult
from accentor.record.artifacts import ArtifactRecord, ArtifactStore
from accentor.record.observe import JsonlSink, TaskObserver


class WorkflowError(RuntimeError):
    """Raised by ``@workflow(return_result=False)`` for failed workflow calls."""

    def __init__(self, result: TaskResult, message: str | None = None) -> None:
        self.result = result
        if message is None:
            if result.diagnostics:
                diagnostic = result.diagnostics[0]
                message = f"Workflow failed: [{diagnostic.code}] {diagnostic.message}"
            else:
                message = "Workflow failed"
        super().__init__(message)


class _WorkflowStageFailure(RuntimeError):
    """Internal non-user-facing control flow for failed stages in workflows."""

    def __init__(self, result: TaskResult) -> None:
        self.result = result
        super().__init__("stage failed")


@dataclass
class _RunState:
    workflow: str | None
    task_id: str
    context: StepContext
    artifact_store: ArtifactStore | None = None
    observer: TaskObserver | None = None
    events: list[TaskEvent] = field(default_factory=list)
    artifacts: list[ArtifactReference] = field(default_factory=list)
    attempt_count: int = 0
    routing_decisions_started: bool = False
    pending_repair_validations: list[Mapping[str, Any]] = field(default_factory=list)

    def emit(self, event: TaskEvent) -> TaskEvent:
        self.events.append(event)
        if self.observer is not None:
            self.observer.emit(event)
        return event

    def add_artifact(
        self,
        artifact: ArtifactReference,
        *,
        stage: str | None = None,
        attempt: int | None = None,
        emit_event: bool = True,
    ) -> ArtifactReference:
        self.artifacts.append(artifact)
        if emit_event:
            self.emit(
                TaskEvent.artifact_recorded(
                    artifact=_artifact_to_dict(artifact),
                    workflow=self.workflow,
                    task=self.task_id,
                    stage=stage,
                    attempt=attempt,
                )
            )
        return artifact

    def add_artifacts(
        self,
        artifacts: Sequence[ArtifactReference],
        *,
        stage: str | None = None,
        attempt: int | None = None,
        emit_event: bool = True,
    ) -> None:
        for artifact in artifacts:
            self.add_artifact(artifact, stage=stage, attempt=attempt, emit_event=emit_event)


_CURRENT_RUNTIME: ContextVar[_RunState | None] = ContextVar("accentor_current_runtime", default=None)


def _current_runtime() -> _RunState | None:
    return _CURRENT_RUNTIME.get()


def _artifact_to_dict(artifact: ArtifactReference) -> dict[str, Any]:
    if isinstance(artifact, ArtifactRecord):
        return artifact.to_dict()
    return dict(artifact)


def _dedupe_artifacts(artifacts: Sequence[ArtifactReference]) -> tuple[ArtifactReference, ...]:
    deduped: list[ArtifactReference] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for artifact in artifacts:
        data = _artifact_to_dict(artifact)
        key = (data.get("name"), data.get("path"), data.get("sha256"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return tuple(deduped)


def _call_with_optional_ctx(
    function: Callable[..., Any],
    ctx: StepContext,
    *args: Any,
    **kwargs: Any,
) -> Any:
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return function(*args, **kwargs)

    parameter = signature.parameters.get("ctx")
    if parameter is None or "ctx" in kwargs:
        return function(*args, **kwargs)
    if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
        return function(ctx, *args, **kwargs)
    return function(*args, ctx=ctx, **kwargs)


def _accepts_parameter(function: Callable[..., Any], parameter_name: str) -> bool:
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return False
    return any(
        parameter.name == parameter_name or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _create_runtime(
    *,
    workflow: str | None,
    task_id: str,
    artifact_root: str | Path | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> _RunState:
    artifact_store = ArtifactStore(artifact_root) if artifact_root is not None else None
    observer = None
    if artifact_store is not None:
        observer = TaskObserver([JsonlSink(artifact_store.root)])

    run_id = uuid.uuid4().hex
    context = StepContext.root(
        run_id=run_id,
        task_id=task_id,
        artifact_store=artifact_store,
        observer=observer,
        metadata=metadata,
    )
    return _RunState(
        workflow=workflow,
        task_id=task_id,
        context=context,
        artifact_store=artifact_store,
        observer=observer,
    )


def _finalize_runtime_result(state: _RunState, result: TaskResult) -> TaskResult:
    if state.observer is not None:
        state.observer.close()

    artifacts = [*state.artifacts, *result.artifacts]
    if state.artifact_store is not None:
        events_path = state.artifact_store.root / "events.jsonl"
        if events_path.exists():
            artifacts.append(
                state.artifact_store.record(
                    "events.jsonl",
                    content_type="application/x-ndjson",
                )
            )

    finalized = TaskResult(
        ok=result.ok,
        output=result.output,
        best_output=result.best_output,
        diagnostics=result.diagnostics,
        attempt_count=max(result.attempt_count, state.attempt_count),
        events=tuple(state.events),
        artifacts=_dedupe_artifacts(artifacts),
    )

    if state.artifact_store is None:
        return finalized

    task_result_artifact = state.artifact_store.write_json("task_result.json", finalized.to_dict())
    return TaskResult(
        ok=finalized.ok,
        output=finalized.output,
        best_output=finalized.best_output,
        diagnostics=finalized.diagnostics,
        attempt_count=finalized.attempt_count,
        events=finalized.events,
        artifacts=_dedupe_artifacts((*finalized.artifacts, task_result_artifact)),
    )


def _failure_result(
    *,
    code: str,
    message: str,
    source: str,
    exception: BaseException | None = None,
    attempt_count: int = 1,
) -> TaskResult:
    details: dict[str, Any] = {}
    if exception is not None:
        details["exception_type"] = type(exception).__name__
    return TaskResult(
        ok=False,
        diagnostics=[
            Diagnostic.error(
                code,
                message,
                source=source,
                details=details,
            )
        ],
        attempt_count=attempt_count,
    )


def _coerce_workflow_output(output: Any, *, state: _RunState) -> TaskResult:
    if isinstance(output, TaskResult):
        state.attempt_count = max(state.attempt_count, output.attempt_count)
        return output
    return TaskResult(
        ok=True,
        output=output,
        best_output=output,
        attempt_count=max(state.attempt_count, 1),
    )


def _run_pending_repair_validations(state: _RunState, result: TaskResult) -> TaskResult:
    if not result.ok or not state.pending_repair_validations:
        return result

    diagnostics = list(result.diagnostics)
    artifacts = list(result.artifacts)
    best_output = result.best_output
    attempt_count = result.attempt_count

    for pending in state.pending_repair_validations:
        validators = pending.get("validators") or ()
        if not validators:
            continue
        stage_name = str(pending.get("stage") or "")
        report = build_validation_report(
            result.output,
            validators,
            max_attempts=1,
            artifact_store=state.artifact_store,
            artifact_root=state.context.artifact_root,
            workflow=state.workflow,
            task=state.task_id,
            stage=stage_name or None,
            write_reports=state.artifact_store is not None,
            metadata=pending.get("metadata") or {},
        )
        for event in report.events:
            state.emit(event)
        state.add_artifacts(report.artifacts, stage=stage_name or None)
        diagnostics.extend(report.diagnostics)
        artifacts.extend(report.artifacts)
        state.attempt_count = max(state.attempt_count, report.attempt_count)
        attempt_count = max(attempt_count, state.attempt_count, report.attempt_count)
        best_output = report.best_output if report.best_output is not None else best_output
        if not report.ok:
            return TaskResult(
                ok=False,
                best_output=best_output,
                diagnostics=tuple(diagnostics),
                attempt_count=attempt_count,
                artifacts=tuple(artifacts),
            )

    return TaskResult(
        ok=True,
        output=result.output,
        best_output=result.output if best_output is None else best_output,
        diagnostics=tuple(diagnostics),
        attempt_count=max(attempt_count, state.attempt_count),
        events=result.events,
        artifacts=tuple(artifacts),
    )


def workflow(
    _function: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    return_result: bool = True,
) -> Callable[..., Any]:
    """Decorate an ordinary Python function as an Accentor workflow."""

    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        workflow_name = name or function.__name__

        @wraps(function)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            artifact_root = kwargs.pop("artifact_root", None)
            state = _create_runtime(
                workflow=workflow_name,
                task_id=workflow_name,
                artifact_root=artifact_root,
                metadata={"workflow": workflow_name},
            )
            token = _CURRENT_RUNTIME.set(state)
            try:
                state.emit(TaskEvent.workflow_started(workflow=workflow_name, task=workflow_name))
                try:
                    output = _call_with_optional_ctx(function, state.context, *args, **kwargs)
                    result = _coerce_workflow_output(output, state=state)
                    result = _run_pending_repair_validations(state, result)
                except _WorkflowStageFailure as exc:
                    result = TaskResult(
                        ok=False,
                        best_output=exc.result.best_output,
                        diagnostics=exc.result.diagnostics,
                        attempt_count=max(state.attempt_count, exc.result.attempt_count),
                    )
                except Exception as exc:  # noqa: BLE001 - workflow boundaries return diagnostics.
                    result = _failure_result(
                        code="workflow.exception",
                        message=f"Workflow {workflow_name!r} raised {type(exc).__name__}: {exc}",
                        source="workflow",
                        exception=exc,
                        attempt_count=max(state.attempt_count, 1),
                    )

                state.emit(
                    TaskEvent.workflow_completed(
                        workflow=workflow_name,
                        task=workflow_name,
                        status="completed" if result.ok else "failed",
                        diagnostics=result.diagnostics,
                    )
                )
                final_result = _finalize_runtime_result(state, result)
            finally:
                _CURRENT_RUNTIME.reset(token)

            if return_result:
                return final_result
            if final_result.ok:
                return final_result.output
            raise WorkflowError(final_result)

        return wrapper

    if _function is not None:
        return decorate(_function)
    return decorate


__all__ = ["WorkflowError", "workflow"]
