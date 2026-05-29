from __future__ import annotations

"""Provider-neutral ordered execution and retry helpers."""

import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from accentor.core.steps.base import Step, StepContext, StepResult
from accentor.core.task.diagnostics import Diagnostic
from accentor.core.task.events import TaskEvent
from accentor.core.task.results import ArtifactReference, TaskResult


Operation = Step | Callable[..., Any]


def _operation_name(operation: Operation, fallback: str) -> str:
    if isinstance(operation, Step):
        return operation.name
    return str(getattr(operation, "__name__", None) or getattr(operation, "name", None) or fallback)


def _default_context(name: str | None = None, *, attempt: int = 0) -> StepContext:
    task_id = name or "composition"
    return StepContext.root(run_id=f"{task_id}-run", task_id=task_id).derive(attempt=attempt)


def _derive_context(ctx: StepContext | None, *, name: str | None = None, attempt: int | None = None) -> StepContext:
    base = ctx or _default_context(name, attempt=attempt or 0)
    updates: dict[str, Any] = {}
    if name is not None and base.stage is None:
        updates["stage"] = name
    if attempt is not None:
        updates["attempt"] = attempt
    return base.derive(**updates) if updates else base


def _callable_accepts_input(function: Callable[..., Any]) -> bool:
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return True
    for parameter in signature.parameters.values():
        if parameter.name == "ctx":
            continue
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        ):
            return True
    return False


def _call_callable(function: Callable[..., Any], current_input: Any, ctx: StepContext) -> Any:
    kwargs: dict[str, Any] = {}
    args: list[Any] = []

    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return function(current_input)

    if "ctx" in signature.parameters:
        parameter = signature.parameters["ctx"]
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            args.append(ctx)
        else:
            kwargs["ctx"] = ctx

    if current_input is not None or _callable_accepts_input(function):
        if _callable_accepts_input(function):
            args.append(current_input)

    return function(*args, **kwargs)


def _exception_result(exc: BaseException, *, operation_name: str, ctx: StepContext) -> StepResult:
    return StepResult.failure(
        diagnostic=Diagnostic.error(
            "step.exception",
            f"Operation {operation_name!r} raised {type(exc).__name__}: {exc}",
            source="core.composition.sequencing",
            details={
                "operation": operation_name,
                "attempt": ctx.attempt,
                "exception_type": type(exc).__name__,
            },
        ),
        step=operation_name,
        attempt=ctx.attempt,
        context=ctx,
    )


def _result_from_task_result(result: TaskResult, *, operation_name: str, ctx: StepContext) -> StepResult:
    return StepResult(
        ok=result.ok,
        output=result.output,
        best_output=result.best_output,
        diagnostics=result.diagnostics,
        events=result.events,
        artifacts=result.artifacts,
        step=operation_name,
        attempt=ctx.attempt,
        context=ctx,
    )


def _run_operation(operation: Operation, current_input: Any, *, ctx: StepContext, fallback_name: str) -> StepResult:
    operation_name = _operation_name(operation, fallback_name)
    try:
        if isinstance(operation, Step):
            if current_input is None:
                return operation.run(ctx)
            return operation.run(ctx, current_input)
        output = _call_callable(operation, current_input, ctx)
    except Exception as exc:  # noqa: BLE001 - sequencing converts operation failures.
        return _exception_result(exc, operation_name=operation_name, ctx=ctx)

    if isinstance(output, StepResult):
        updates: dict[str, Any] = {}
        if output.step is None:
            updates["step"] = operation_name
        if output.context is None:
            updates["context"] = ctx
        if output.attempt is None:
            updates["attempt"] = ctx.attempt
        return output.with_updates(**updates) if updates else output
    if isinstance(output, TaskResult):
        return _result_from_task_result(output, operation_name=operation_name, ctx=ctx)
    return StepResult.success(output, step=operation_name, attempt=ctx.attempt, context=ctx)


def _aggregate_result(
    *,
    ok: bool,
    output: Any,
    best_output: Any,
    diagnostics: Sequence[Diagnostic],
    events: Sequence[TaskEvent],
    artifacts: Sequence[ArtifactReference],
    attempt_count: int,
) -> TaskResult:
    return TaskResult(
        ok=ok,
        output=output,
        best_output=best_output,
        diagnostics=tuple(diagnostics),
        events=tuple(events),
        artifacts=tuple(artifacts),
        attempt_count=attempt_count,
    )


def _extend_from_step(
    result: StepResult,
    *,
    diagnostics: list[Diagnostic],
    events: list[TaskEvent],
    artifacts: list[ArtifactReference],
) -> None:
    diagnostics.extend(result.diagnostics)
    events.extend(result.events)
    artifacts.extend(result.artifacts)


def sequence(
    steps: Sequence[Operation],
    *,
    initial_input: Any = None,
    ctx: StepContext | None = None,
    stop_on_failure: bool = True,
    name: str | None = None,
) -> TaskResult:
    """Run steps in order, passing each successful output to the next step."""

    current = initial_input
    best_output = initial_input
    diagnostics: list[Diagnostic] = []
    events: list[TaskEvent] = []
    artifacts: list[ArtifactReference] = []
    attempt_count = 0

    if not steps:
        return _aggregate_result(
            ok=True,
            output=current,
            best_output=current,
            diagnostics=diagnostics,
            events=events,
            artifacts=artifacts,
            attempt_count=0,
        )

    for index, operation in enumerate(steps):
        operation_name = _operation_name(operation, f"step_{index}")
        step_ctx = _derive_context(ctx, name=name or operation_name)
        result = _run_operation(operation, current, ctx=step_ctx, fallback_name=f"step_{index}")
        attempt_count += max(result.to_task_result().attempt_count, 1)
        _extend_from_step(result, diagnostics=diagnostics, events=events, artifacts=artifacts)

        if result.best_output is not None:
            best_output = result.best_output
        elif result.output is not None:
            best_output = result.output

        if result.ok:
            current = result.output
            continue

        if stop_on_failure:
            return _aggregate_result(
                ok=False,
                output=None,
                best_output=best_output,
                diagnostics=diagnostics,
                events=events,
                artifacts=artifacts,
                attempt_count=attempt_count,
            )

    return _aggregate_result(
        ok=True,
        output=current,
        best_output=best_output,
        diagnostics=diagnostics,
        events=events,
        artifacts=artifacts,
        attempt_count=attempt_count,
    )


def _should_retry(retry_on: Callable[..., bool] | None, result: StepResult, attempt: int) -> bool:
    if retry_on is None:
        return not result.ok
    try:
        signature = inspect.signature(retry_on)
    except (TypeError, ValueError):
        return bool(retry_on(result))
    kwargs: dict[str, Any] = {}
    if "attempt" in signature.parameters:
        kwargs["attempt"] = attempt
    return bool(retry_on(result, **kwargs))


def _notify_attempt_failure(callback: Callable[..., Any] | None, result: StepResult, attempt: int) -> None:
    if callback is None:
        return
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        callback(result)
        return
    kwargs: dict[str, Any] = {}
    if "attempt" in signature.parameters:
        kwargs["attempt"] = attempt
    callback(result, **kwargs)


def retry(
    operation: Operation,
    *,
    max_attempts: int = 1,
    ctx: StepContext | None = None,
    retry_on: Callable[..., bool] | None = None,
    on_attempt_failure: Callable[..., Any] | None = None,
    name: str | None = None,
) -> TaskResult:
    """Run one operation until success, non-retryable failure, or exhaustion."""

    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise TypeError("max_attempts must be an int")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    operation_name = name or _operation_name(operation, "retry")
    diagnostics: list[Diagnostic] = []
    events: list[TaskEvent] = []
    artifacts: list[ArtifactReference] = []
    best_output: Any = None
    final_output: Any = None

    for attempt in range(max_attempts):
        attempt_ctx = _derive_context(ctx, name=operation_name, attempt=attempt)
        events.append(
            TaskEvent.attempt_started(
                attempt=attempt,
                stage=operation_name,
                task=attempt_ctx.task_id,
            )
        )
        result = _run_operation(operation, final_output, ctx=attempt_ctx, fallback_name=operation_name)
        _extend_from_step(result, diagnostics=diagnostics, events=events, artifacts=artifacts)
        if result.best_output is not None:
            best_output = result.best_output
        elif result.output is not None:
            best_output = result.output

        events.append(
            TaskEvent.attempt_completed(
                attempt=attempt,
                stage=operation_name,
                task=attempt_ctx.task_id,
                status="completed" if result.ok else "failed",
                diagnostics=result.diagnostics,
            )
        )

        if result.ok:
            return _aggregate_result(
                ok=True,
                output=result.output,
                best_output=result.best_output if result.best_output is not None else result.output,
                diagnostics=diagnostics,
                events=events,
                artifacts=artifacts,
                attempt_count=attempt + 1,
            )

        final_output = result.output
        _notify_attempt_failure(on_attempt_failure, result, attempt)
        if attempt < max_attempts - 1 and _should_retry(retry_on, result, attempt):
            continue
        if attempt < max_attempts - 1:
            return _aggregate_result(
                ok=False,
                output=None,
                best_output=best_output,
                diagnostics=diagnostics,
                events=events,
                artifacts=artifacts,
                attempt_count=attempt + 1,
            )

    diagnostics.append(
        Diagnostic.error(
            "retry.exhausted",
            f"Operation {operation_name!r} failed after {max_attempts} attempts.",
            source="core.composition.sequencing",
            details={"operation": operation_name, "max_attempts": max_attempts},
        )
    )
    return _aggregate_result(
        ok=False,
        output=None,
        best_output=best_output,
        diagnostics=diagnostics,
        events=events,
        artifacts=artifacts,
        attempt_count=max_attempts,
    )


__all__ = ["retry", "sequence"]
